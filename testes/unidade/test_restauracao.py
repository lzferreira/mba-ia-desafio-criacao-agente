"""C2, C3, C5 — o comando de restauração volta ao estado de `dados/` e não o toca."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from assistente import armazenamento
from testes.conftest import RAIZ, PYTHON_DO_PROJETO, ambiente_sem_chave

SEMENTES = {
    "apartamentos": 6,
    "areas": 3,
    "reservas": 3,
    "visitantes": 2,
}


def _restaurar(raiz: Path) -> subprocess.CompletedProcess:
    ambiente = ambiente_sem_chave()
    ambiente["PYTHONPATH"] = str(raiz)
    return subprocess.run(
        [str(PYTHON_DO_PROJETO), "-m", "assistente.restaurar"],
        cwd=raiz,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _contar(conexao, tabela: str, onde: str = "") -> int:
    return conexao.execute(f"SELECT count(*) FROM {tabela} {onde}").fetchone()[0]


def test_restauracao_em_clone_limpo_semeia_as_quatro_tabelas(raiz_isolada: Path) -> None:
    banco_de_sessoes = raiz_isolada / "var" / "sessoes.db"
    banco_de_sessoes.parent.mkdir(parents=True, exist_ok=True)
    banco_de_sessoes.write_bytes(b"sessoes antigas")

    concluido = _restaurar(raiz_isolada)
    assert concluido.returncode == 0, concluido.stderr

    conexao = armazenamento.conectar(raiz_isolada / "var" / "condominio.db")
    try:
        assert _contar(conexao, "apartamentos") == SEMENTES["apartamentos"]
        assert _contar(conexao, "areas") == SEMENTES["areas"]
        assert _contar(conexao, "reservas", "WHERE ativa = 1") == SEMENTES["reservas"]
        assert _contar(conexao, "visitantes") == SEMENTES["visitantes"]

        esperadas = json.loads((RAIZ / "dados" / "reservas.json").read_text("utf-8"))
        gravadas = {
            linha["codigo"]: (linha["apartamento"], linha["area"], linha["data"])
            for linha in conexao.execute(
                "SELECT codigo, apartamento, area, data FROM reservas WHERE ativa = 1"
            )
        }
        assert gravadas == {
            r["codigo"]: (r["apartamento"], r["area"], r["data"]) for r in esperadas
        }

        areas = json.loads((RAIZ / "dados" / "areas.json").read_text("utf-8"))
        assert {l["id"]: (l["nome"], l["taxa"]) for l in conexao.execute(
            "SELECT id, nome, taxa FROM areas"
        )} == {a["id"]: (a["nome"], float(a["taxa"])) for a in areas}
    finally:
        conexao.close()

    assert not banco_de_sessoes.exists()


def test_restauracao_descarta_alteracoes_e_volta_ao_estado_inicial(
    raiz_isolada: Path,
) -> None:
    assert _restaurar(raiz_isolada).returncode == 0
    banco = raiz_isolada / "var" / "condominio.db"

    conexao = armazenamento.conectar(banco)
    try:
        armazenamento.gravar_reserva(conexao, "101", "salao-de-festas", "2030-04-20")
        armazenamento.cancelar_reserva(conexao, "101", "quadra", "2030-03-09")
        armazenamento.gravar_visitante(conexao, "101", "Joana Ribeiro", "2030-04-21")
    finally:
        conexao.close()

    assert _restaurar(raiz_isolada).returncode == 0

    conexao = armazenamento.conectar(banco)
    try:
        assert _contar(conexao, "reservas") == SEMENTES["reservas"]
        assert _contar(conexao, "reservas", "WHERE ativa = 1") == SEMENTES["reservas"]
        assert armazenamento.reservas_do_apartamento(conexao, "101") == [
            {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
        ]
        assert sorted(
            linha["nome"] for linha in conexao.execute("SELECT nome FROM visitantes")
        ) == ["Marina Duarte", "Paulo Nogueira"]
    finally:
        conexao.close()


def test_dados_permanecem_identicos_ao_repositorio_base(raiz_isolada: Path) -> None:
    assert _restaurar(raiz_isolada).returncode == 0
    banco = raiz_isolada / "var" / "condominio.db"
    conexao = armazenamento.conectar(banco)
    try:
        armazenamento.gravar_reserva(conexao, "101", "churrasqueira", "2030-06-01")
        armazenamento.gravar_visitante(conexao, "101", "Joana Ribeiro", "2030-04-21")
    finally:
        conexao.close()
    assert _restaurar(raiz_isolada).returncode == 0

    sujo = subprocess.run(
        ["git", "status", "--porcelain", "dados/"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert sujo.returncode == 0
    assert sujo.stdout == ""
