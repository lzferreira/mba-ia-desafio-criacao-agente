"""C32, C37, C39 — o banco é quem garante exclusividade e código inédito."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from assistente import armazenamento
from testes.conftest import RAIZ

CODIGOS_SEMEADOS = {"RSV-1377", "RSV-4821", "RSV-2950"}


@pytest.fixture
def banco(tmp_path: Path) -> Path:
    caminho = tmp_path / "condominio.db"
    armazenamento.restaurar(caminho, tmp_path / "sessoes.db", RAIZ / "dados")
    return caminho


def test_cancelar_mantem_a_linha_com_ativa_zero_e_o_codigo_reservado(
    banco: Path,
) -> None:
    conexao = armazenamento.conectar(banco)
    try:
        codigo = armazenamento.cancelar_reserva(conexao, "101", "quadra", "2030-03-09")
        assert codigo == "RSV-1377"

        linha = conexao.execute(
            "SELECT apartamento, area, data, ativa FROM reservas WHERE codigo = ?",
            ("RSV-1377",),
        ).fetchone()
        assert linha is not None, "cancelar não pode apagar a linha"
        assert linha["ativa"] == 0
        assert (linha["apartamento"], linha["area"], linha["data"]) == (
            "101",
            "quadra",
            "2030-03-09",
        )
        assert armazenamento.reservas_do_apartamento(conexao, "101") == []

        # O código continua ocupado: a mesma área e data podem ser reservadas de
        # novo, mas nunca com o código da reserva cancelada.
        novo = armazenamento.gravar_reserva(conexao, "101", "quadra", "2030-03-09")
        assert novo != "RSV-1377"
    finally:
        conexao.close()


def test_codigos_gerados_sao_distintos_entre_si_e_dos_semeados(banco: Path) -> None:
    conexao = armazenamento.conectar(banco)
    try:
        gerados = [
            armazenamento.gravar_reserva(conexao, "101", "quadra", f"2030-05-{dia:02d}")
            for dia in range(1, 21)
        ]
    finally:
        conexao.close()

    assert len(set(gerados)) == len(gerados)
    assert set(gerados).isdisjoint(CODIGOS_SEMEADOS)


def test_codigo_nunca_reaproveita_o_de_uma_reserva_cancelada(banco: Path) -> None:
    """Enche a faixa inteira menos um código, com linhas canceladas, e cobra o resto.

    Se a geração olhasse só as reservas ativas, sobrariam 8999 códigos livres e o
    sorteio quase certamente devolveria um deles. Olhando a tabela inteira, só
    existe uma saída possível.
    """
    conexao = armazenamento.conectar(banco)
    try:
        conexao.execute("BEGIN IMMEDIATE")
        conexao.executemany(
            "INSERT OR IGNORE INTO reservas (codigo, apartamento, area, data, ativa)"
            " VALUES (?, '101', 'quadra', '2029-01-01', 0)",
            [(f"RSV-{numero}",) for numero in range(1000, 9999)],
        )
        conexao.execute("COMMIT")

        assert armazenamento._gerar_codigo(conexao) == "RSV-9999"
    finally:
        conexao.close()


def test_indice_unico_recusa_a_segunda_gravacao_concorrente(banco: Path) -> None:
    """Duas threads gravam a mesma área e data ao mesmo tempo; uma só vence.

    Nenhuma das duas consulta a agenda antes: elas vão direto ao INSERT. Quem
    recusa a segunda é o índice único parcial, no instante do commit — que é
    exatamente o que a Garantia 5 exige e o que uma conferência prévia não daria.
    """
    largada = threading.Barrier(2)
    resultados: list[tuple[str, object]] = []
    trava = threading.Lock()

    def gravar(apartamento: str) -> None:
        conexao = armazenamento.conectar(banco)
        try:
            largada.wait(timeout=10)
            try:
                codigo = armazenamento.gravar_reserva(
                    conexao, apartamento, "salao-de-festas", "2030-05-11"
                )
                desfecho = ("venceu", codigo)
            except armazenamento.DataIndisponivel as recusa:
                desfecho = ("recusado", recusa)
            except sqlite3.Error as erro:  # pragma: no cover - seria falha real
                desfecho = ("erro", erro)
            with trava:
                resultados.append(desfecho)
        finally:
            conexao.close()

    fios = [
        threading.Thread(target=gravar, args=("101",)),
        threading.Thread(target=gravar, args=("201",)),
    ]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join(timeout=30)

    desfechos = sorted(d for d, _ in resultados)
    assert desfechos == ["recusado", "venceu"], resultados

    conexao = armazenamento.conectar(banco)
    try:
        ativas = conexao.execute(
            "SELECT count(*) FROM reservas"
            " WHERE area = 'salao-de-festas' AND data = '2030-05-11' AND ativa = 1"
        ).fetchone()[0]
        assert ativas == 1
    finally:
        conexao.close()


def test_o_indice_parcial_deixa_reservar_de_novo_depois_do_cancelamento(
    banco: Path,
) -> None:
    """A exclusividade vale entre as ativas, não entre todas as linhas."""
    conexao = armazenamento.conectar(banco)
    try:
        with pytest.raises(armazenamento.DataIndisponivel):
            armazenamento.gravar_reserva(conexao, "101", "quadra", "2030-03-09")

        armazenamento.cancelar_reserva(conexao, "101", "quadra", "2030-03-09")
        assert armazenamento.gravar_reserva(conexao, "201", "quadra", "2030-03-09")
    finally:
        conexao.close()
