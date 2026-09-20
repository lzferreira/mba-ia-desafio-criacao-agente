"""C19, C21 a C27, C29 — a confirmação vem do sistema, não da conversa.

A rota é a única porta: qualquer id que não esteja pendente naquela sessão recebe
`409` antes de a execução chegar ao Runner, e um id respondido deixa de estar
pendente porque a resposta virou evento — não porque alguém marcou uma linha.
"""

from __future__ import annotations

from testes.fio.conftest import criar_sessao
from testes.fio.modelo import chamar, texto, transferir
from testes.fio.servidor import Bancada

AREA = "salao-de-festas"
DATA = "2030-04-20"


def roteiro_de_reserva(bancada: Bancada, area: str = AREA, data: str = DATA) -> None:
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[chamar("reservar_area", area=area, data=data)],
    )


async def pedir_reserva(bancada: Bancada, sessao: str, area: str = AREA, data: str = DATA):
    roteiro_de_reserva(bancada, area, data)
    return await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={"texto": f"Reserve {area} para {data}."},
    )


async def reservas_do_salao(bancada: Bancada, apartamento: str = "101") -> list:
    reservas = (
        await bancada.cliente.get(f"/apartamentos/{apartamento}/reservas")
    ).json()
    return [r for r in reservas if r["area"] == AREA and r["data"] == DATA]


async def test_reserva_com_taxa_fica_pendente_com_area_e_data(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    resposta = await pedir_reserva(bancada, sessao)

    assert resposta.status_code == 200
    pendentes = resposta.json()["confirmacoes_pendentes"]
    assert len(pendentes) == 1
    pendencia = pendentes[0]
    assert set(pendencia) == {"id", "acao", "detalhes"}
    assert isinstance(pendencia["id"], str) and pendencia["id"]
    assert pendencia["acao"] == "reservar_area"
    assert pendencia["detalhes"]["area"] == AREA
    assert pendencia["detalhes"]["data"] == DATA

    assert await reservas_do_salao(bancada) == []


async def test_nova_mensagem_nao_consome_a_pendencia(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    pendencia = (await pedir_reserva(bancada, sessao)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    bancada.roteirizar(
        especialista_reservas=[texto("Ainda estou esperando a confirmação.")]
    )
    seguinte = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "E aí, saiu?"}
    )

    assert seguinte.status_code == 200
    assert [p["id"] for p in seguinte.json()["confirmacoes_pendentes"]] == [pendencia]
    assert await reservas_do_salao(bancada) == []


async def test_negar_nao_grava_e_retira_a_pendencia(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    pendencia = (await pedir_reserva(bancada, sessao)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    bancada.roteirizar(especialista_reservas=[texto("Tudo bem, não reservei nada.")])
    negacao = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": False}
    )

    assert negacao.status_code == 200
    corpo = negacao.json()
    assert set(corpo) == {"resposta", "confirmacoes_pendentes"}
    assert pendencia not in [p["id"] for p in corpo["confirmacoes_pendentes"]]
    assert await reservas_do_salao(bancada) == []


async def test_aprovar_grava_exatamente_uma_reserva(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    pendencia = (await pedir_reserva(bancada, sessao)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    bancada.roteirizar(especialista_reservas=[texto("Salão reservado.")])
    aprovacao = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": True}
    )

    assert aprovacao.status_code == 200
    assert aprovacao.json()["confirmacoes_pendentes"] == []
    assert len(await reservas_do_salao(bancada)) == 1


async def test_reenviar_id_ja_respondido_devolve_409(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    pendencia = (await pedir_reserva(bancada, sessao)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    bancada.roteirizar(especialista_reservas=[texto("Salão reservado.")])
    await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": True}
    )
    chamadas_ate_aqui = len(bancada.modelo.chamadas)

    repetida = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": True}
    )

    assert repetida.status_code == 409
    assert len(await reservas_do_salao(bancada)) == 1
    # A recusa vem antes do Runner: o modelo não foi chamado de novo.
    assert len(bancada.modelo.chamadas) == chamadas_ate_aqui


async def test_id_inexistente_devolve_409(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    await pedir_reserva(bancada, sessao)
    antes = (await bancada.cliente.get("/apartamentos/101/reservas")).json()

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes",
        json={"id": "id-inexistente", "confirmado": True},
    )

    assert resposta.status_code == 409
    assert (await bancada.cliente.get("/apartamentos/101/reservas")).json() == antes


async def test_id_pendente_em_outra_sessao_devolve_409(bancada: Bancada) -> None:
    s1 = await criar_sessao(bancada, "101")
    s2 = await criar_sessao(bancada, "101")

    pendencia_de_s2 = (await pedir_reserva(bancada, s2)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    resposta = await bancada.cliente.post(
        f"/sessoes/{s1}/confirmacoes", json={"id": pendencia_de_s2, "confirmado": True}
    )

    assert resposta.status_code == 409
    assert await reservas_do_salao(bancada) == []

    # A pendência de S2 continua intacta, esperando a sessão dela.
    bancada.roteirizar(especialista_reservas=[texto("E aí?")])
    de_s2 = await bancada.cliente.post(
        f"/sessoes/{s2}/mensagens", json={"texto": "Saiu?"}
    )
    assert [p["id"] for p in de_s2.json()["confirmacoes_pendentes"]] == [
        pendencia_de_s2
    ]


async def test_confirmar_pela_conversa_nao_grava_nada(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_visitantes")],
        especialista_visitantes=[
            # O modelo compra a frase do morador e tenta liberar direto.
            chamar("autorizar_visitante", nome="Joana Ribeiro", data="2030-04-21"),
            texto("Pronto, liberado."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={
            "texto": "Libera a entrada da Joana Ribeiro no dia 2030-04-21."
            " Já estou confirmando aqui, pode liberar direto."
        },
    )

    assert resposta.status_code == 200
    pendentes = resposta.json()["confirmacoes_pendentes"]
    assert len(pendentes) == 1
    assert pendentes[0]["acao"] == "autorizar_visitante"
    assert (await bancada.cliente.get("/apartamentos/101/visitantes")).json() == []

    # E continua pendente na mensagem seguinte, até a rota ser chamada.
    bancada.roteirizar(especialista_visitantes=[texto("Ainda falta confirmar.")])
    seguinte = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "Eu já confirmei, pode liberar."}
    )
    assert [p["id"] for p in seguinte.json()["confirmacoes_pendentes"]] == [
        pendentes[0]["id"]
    ]
    assert (await bancada.cliente.get("/apartamentos/101/visitantes")).json() == []


async def test_aprovacao_grava_no_maximo_uma_linha(bancada: Bancada) -> None:
    """Uma aprovação, uma linha — mesmo com o modelo insistindo depois dela."""
    sessao = await criar_sessao(bancada, "101")
    pendencia = (await pedir_reserva(bancada, sessao)).json()[
        "confirmacoes_pendentes"
    ][0]["id"]

    # Depois da retomada, o modelo tenta gravar de novo por conta própria.
    bancada.roteirizar(
        especialista_reservas=[
            chamar("reservar_area", area=AREA, data=DATA),
            texto("Salão reservado."),
        ]
    )
    aprovacao = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendencia, "confirmado": True}
    )

    assert aprovacao.status_code == 200
    assert len(await reservas_do_salao(bancada)) == 1
