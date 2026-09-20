"""C37, C44 — a recusa do banco vira resposta normal, e o apartamento é o da sessão."""

from __future__ import annotations

from pathlib import Path

import pytest

from assistente import armazenamento, dominio
from testes.conftest import RAIZ


@pytest.fixture
def conexao(tmp_path: Path):
    caminho = tmp_path / "condominio.db"
    armazenamento.restaurar(caminho, tmp_path / "sessoes.db", RAIZ / "dados")
    aberta = armazenamento.conectar(caminho)
    try:
        yield aberta
    finally:
        aberta.close()


def test_recusa_do_banco_vira_resposta_normal(conexao, monkeypatch) -> None:
    """A agenda diz livre, o índice recusa no commit, e o morador recebe um 200.

    O cenário é o do passo 14: entre a conferência e a gravação, a outra reserva
    entrou. A tool não pode transformar isso em erro de servidor.
    """
    assert dominio.disponibilidade(conexao, "salao-de-festas", "2030-05-11") == {
        "area": "Salão de festas",
        "data": "2030-05-11",
        "disponivel": True,
    }

    def perdeu_a_corrida(*_, **__):
        raise armazenamento.DataIndisponivel("salao-de-festas", "2030-05-11")

    monkeypatch.setattr(armazenamento, "gravar_reserva", perdeu_a_corrida)

    resultado = dominio.reservar(conexao, "101", "salao-de-festas", "2030-05-11")

    assert resultado["ok"] is False
    assert resultado["motivo"] == "indisponivel"
    assert "não está disponível" in resultado["mensagem"]
    # E a recusa não conta de quem é: nem código, nem apartamento.
    assert "RSV" not in resultado["mensagem"]
    assert "302" not in resultado["mensagem"]


def test_disponibilidade_nunca_devolve_o_dono(conexao) -> None:
    ocupada = dominio.disponibilidade(conexao, "salao-de-festas", "2030-03-16")
    assert ocupada == {
        "area": "Salão de festas",
        "data": "2030-03-16",
        "disponivel": False,
    }
    assert "RSV-4821" not in str(ocupada)
    assert "302" not in str(ocupada)


def test_reservar_recusa_area_inexistente_nomeando_as_tres(conexao) -> None:
    resultado = dominio.reservar(conexao, "101", "piscina", "2030-04-06")
    assert resultado["ok"] is False
    assert resultado["motivo"] == "area_inexistente"
    for nome in ("Salão de festas", "Churrasqueira", "Quadra poliesportiva"):
        assert nome in resultado["mensagem"]


def test_reservar_recusa_data_que_ja_e_do_proprio_apartamento(conexao) -> None:
    resultado = dominio.reservar(conexao, "101", "quadra", "2030-03-09")
    assert resultado["ok"] is False
    assert resultado["motivo"] == "ja_e_sua"
    assert "já é sua" in resultado["mensagem"]


def test_cancelar_alheia_e_inexistente_respondem_a_mesma_frase(conexao) -> None:
    alheia = dominio.cancelar(conexao, "101", "salao-de-festas", "2030-03-16")
    inexistente = dominio.cancelar(conexao, "101", "salao-de-festas", "2031-12-31")

    assert alheia["ok"] is False and inexistente["ok"] is False
    assert alheia["motivo"] == inexistente["motivo"] == "sem_reserva_sua"
    # Distinguir os dois contaria que a reserva do vizinho existe.
    assert alheia["mensagem"].replace("2030-03-16", "X") == inexistente[
        "mensagem"
    ].replace("2031-12-31", "X")
    assert "RSV-4821" not in alheia["mensagem"]
    assert armazenamento.reservas_do_apartamento(conexao, "302") == [
        {"codigo": "RSV-4821", "area": "salao-de-festas", "data": "2030-03-16"}
    ]


def test_autorizacao_usa_o_apartamento_do_state_e_ignora_o_citado(conexao) -> None:
    """A função recebe o apartamento da sessão; não existe caminho para outro.

    O nome do visitante pode vir cheio de texto do morador — inclusive citando o
    302 — e isso não muda a linha gravada, porque o apartamento é parâmetro de
    quem chama, e quem chama lê do state.
    """
    dominio.autorizar_visitante(
        conexao, "101", "Joana Ribeiro (moradora do 302)", "2030-04-21"
    )

    linhas = list(conexao.execute("SELECT apartamento, nome, data FROM visitantes"))
    gravada = [l for l in linhas if l["nome"].startswith("Joana")]
    assert len(gravada) == 1
    assert gravada[0]["apartamento"] == "101"
    assert armazenamento.visitantes_do_apartamento(conexao, "302") == [
        {"nome": "Marina Duarte", "data": "2030-03-16"}
    ]


def test_autorizacao_recusa_nome_vazio_ou_data_fora_do_formato(conexao) -> None:
    sem_nome = dominio.autorizar_visitante(conexao, "101", "   ", "2030-04-21")
    sem_data = dominio.autorizar_visitante(conexao, "101", "Joana Ribeiro", "amanhã")

    assert sem_nome["ok"] is False and sem_nome["motivo"] == "sem_nome"
    assert sem_data["ok"] is False and sem_data["motivo"] == "data_invalida"
    assert armazenamento.visitantes_do_apartamento(conexao, "101") == []
