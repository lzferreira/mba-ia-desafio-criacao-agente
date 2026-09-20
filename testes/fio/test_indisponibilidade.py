"""Quando o Gemini falha, a API diz que falhou — e não grava nada.

Nenhum passo do avaliador exercita este caminho; ele é o default escrito para a
pergunta 1 em aberto da task. A prova existe porque a alternativa silenciosa —
devolver `200` com uma `resposta` inventada — é exatamente o tipo de falha que o
resto deste projeto passa o tempo todo tentando impedir.
"""

from __future__ import annotations

import httpx
import pytest

from testes.fio.conftest import criar_sessao
from testes.fio.servidor import Bancada


class ModeloQueCai(Exception):
    pass


@pytest.fixture
def bancada_que_cai(bancada: Bancada) -> Bancada:
    async def cair(*_, **__):
        raise ModeloQueCai("429 RESOURCE_EXHAUSTED: quota do AI Studio esgotada")

    bancada.cliente._transport.app.state.aplicacao.conversar = cair
    return bancada


async def test_falha_do_modelo_vira_503_sem_gravar_nada(bancada_que_cai: Bancada) -> None:
    sessao = await criar_sessao(bancada_que_cai, "101")
    antes = (await bancada_que_cai.cliente.get("/apartamentos/101/reservas")).json()

    resposta = await bancada_que_cai.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={"texto": "Reserve a quadra para 2030-04-06."},
    )

    assert resposta.status_code == 503
    corpo = resposta.json()
    assert "detail" in corpo
    # Nenhuma `resposta` de sucesso inventada no lugar do erro.
    assert "resposta" not in corpo
    assert (
        await bancada_que_cai.cliente.get("/apartamentos/101/reservas")
    ).json() == antes


async def test_falha_do_modelo_na_rota_de_confirmacoes_tambem_e_503(
    bancada: Bancada,
) -> None:
    sessao = await criar_sessao(bancada, "101")
    from testes.fio.modelo import chamar, transferir

    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("reservar_area", area="salao-de-festas", data="2030-04-20")
        ],
    )
    pedido = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={"texto": "Reserve o salão de festas para 2030-04-20."},
    )
    pendencia = pedido.json()["confirmacoes_pendentes"][0]["id"]

    async def cair(*_, **__):
        raise ModeloQueCai("503 UNAVAILABLE")

    bancada.cliente._transport.app.state.aplicacao.conversar = cair

    aprovacao = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes",
        json={"id": pendencia, "confirmado": True},
    )

    assert aprovacao.status_code == 503
    assert "detail" in aprovacao.json()
    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    assert [r for r in reservas if r["data"] == "2030-04-20"] == []


async def test_id_recusado_com_409_nao_chega_a_chamar_o_modelo(bancada: Bancada) -> None:
    """O `409` vem antes do Runner, então uma falha de modelo não o transforma em `503`."""
    sessao = await criar_sessao(bancada, "101")

    async def cair(*_, **__):
        raise ModeloQueCai("nunca deveria ser chamado")

    bancada.cliente._transport.app.state.aplicacao.conversar = cair

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes",
        json={"id": "id-inexistente", "confirmado": True},
    )

    assert resposta.status_code == 409
