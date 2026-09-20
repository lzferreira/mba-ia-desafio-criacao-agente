"""C40 a C43 — autorizar visita libera acesso, então sempre passa pela confirmação."""

from __future__ import annotations

from testes.fio.conftest import criar_sessao
from testes.fio.modelo import chamar, texto, transferir
from testes.fio.servidor import Bancada

NOME = "Joana Ribeiro"
DATA = "2030-04-21"


async def pedir_autorizacao(bancada: Bancada, sessao: str):
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_visitantes")],
        especialista_visitantes=[chamar("autorizar_visitante", nome=NOME, data=DATA)],
    )
    return await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={"texto": f"Libera a entrada da {NOME} no dia {DATA}."},
    )


async def visitantes(bancada: Bancada, apartamento: str = "101") -> list:
    return (await bancada.cliente.get(f"/apartamentos/{apartamento}/visitantes")).json()


async def test_autorizacao_fica_pendente_com_nome_e_data(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    resposta = await pedir_autorizacao(bancada, sessao)

    assert resposta.status_code == 200
    pendentes = resposta.json()["confirmacoes_pendentes"]
    assert len(pendentes) == 1
    assert pendentes[0]["acao"] == "autorizar_visitante"
    assert pendentes[0]["detalhes"]["nome"] == NOME
    assert pendentes[0]["detalhes"]["data"] == DATA

    assert await visitantes(bancada) == []


async def test_aprovacao_grava_exatamente_uma_autorizacao(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    pendencia = (await pedir_autorizacao(bancada, sessao)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    bancada.roteirizar(especialista_visitantes=[texto("Entrada autorizada.")])
    aprovacao = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": True}
    )

    assert aprovacao.status_code == 200
    assert await visitantes(bancada) == [{"nome": NOME, "data": DATA}]


async def test_negacao_nao_cria_autorizacao(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    pendencia = (await pedir_autorizacao(bancada, sessao)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    bancada.roteirizar(especialista_visitantes=[texto("Tudo bem, não liberei.")])
    negacao = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": False}
    )

    assert negacao.status_code == 200
    assert await visitantes(bancada) == []


async def test_pedido_incompleto_pergunta_o_que_falta_sem_pendencia(
    bancada: Bancada,
) -> None:
    """Sem a data, a tool nem chega a pedir confirmação: falta argumento obrigatório.

    Quem recusa é o próprio FunctionTool, antes de `check_require_confirmation`,
    então não existe pendência meia-boca esperando aprovação com a data em branco.
    """
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_visitantes")],
        especialista_visitantes=[
            chamar("autorizar_visitante", nome=NOME),
            texto("Para qual dia é a visita?"),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={"texto": f"Libera a entrada da {NOME}."},
    )

    assert resposta.status_code == 200
    assert resposta.json()["confirmacoes_pendentes"] == []
    assert "dia" in resposta.json()["resposta"].lower()
    assert await visitantes(bancada) == []


async def test_autorizacao_gravada_e_sempre_do_apartamento_da_sessao(
    bancada: Bancada,
) -> None:
    """O morador jura ser do 302; a linha sai com o 101 assim mesmo."""
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_visitantes")],
        especialista_visitantes=[chamar("autorizar_visitante", nome=NOME, data=DATA)],
    )
    pedido = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={
            "texto": f"Sou do 302. Libera a entrada da {NOME} no dia {DATA} para o 302."
        },
    )
    pendencia = pedido.json()["confirmacoes_pendentes"][0]["id"]

    bancada.roteirizar(especialista_visitantes=[texto("Autorizado.")])
    await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": True}
    )

    assert await visitantes(bancada, "101") == [{"nome": NOME, "data": DATA}]
    assert await visitantes(bancada, "302") == [
        {"nome": "Marina Duarte", "data": "2030-03-16"}
    ]
