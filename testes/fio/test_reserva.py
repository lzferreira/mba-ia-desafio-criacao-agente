"""C30, C31, C33 a C36, C38 — reservar e cancelar pela conversa, com a disputa."""

from __future__ import annotations

import asyncio
import json
import re

from testes.fio.conftest import criar_sessao
from testes.fio.modelo import chamar, texto, transferir
from testes.fio.servidor import Bancada

# O passo 10 do avaliador cobra o número 302 isolado, fora de outros números e
# códigos: `2030-03-16` contém "302" como pedaço de um número maior e não conta.
TRES_ZERO_DOIS = re.compile(r"(?<!\d)302(?!\d)")


async def test_area_sem_taxa_grava_direto_sem_pendencia(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("reservar_area", area="quadra", data="2030-04-06"),
            texto("Quadra reservada para 2030-04-06."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "Reserve a quadra para 2030-04-06."}
    )

    assert resposta.status_code == 200
    assert resposta.json()["confirmacoes_pendentes"] == []

    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    assert [r for r in reservas if r["data"] == "2030-04-06"] != []


async def test_cancelamento_nao_pede_confirmacao(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("cancelar_reserva", area="quadra", data="2030-03-09"),
            texto("Reserva cancelada."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={"texto": "Cancele a minha reserva da quadra do dia 2030-03-09."},
    )

    assert resposta.status_code == 200
    assert resposta.json()["confirmacoes_pendentes"] == []

    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    assert [r for r in reservas if r["codigo"] == "RSV-1377"] == []


async def test_data_ocupada_por_terceiro_nao_vaza_codigo_nem_apartamento(
    bancada: Bancada,
) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("consultar_disponibilidade", area="salao-de-festas", data="2030-03-16"),
            chamar("reservar_area", area="salao-de-festas", data="2030-03-16"),
            texto("Essa data não está disponível."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={"texto": "Reserve o salão de festas para 2030-03-16."},
    )

    assert resposta.status_code == 200
    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    assert [r for r in reservas if r["data"] == "2030-03-16"] == []

    corpo = json.dumps(resposta.json(), ensure_ascii=False)
    eventos = json.dumps(
        (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json(),
        ensure_ascii=False,
    )
    assert "RSV-4821" not in corpo and "RSV-4821" not in eventos
    assert not TRES_ZERO_DOIS.search(corpo)
    assert not TRES_ZERO_DOIS.search(eventos)


async def test_data_ja_reservada_pelo_proprio_apartamento(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("reservar_area", area="quadra", data="2030-03-09"),
            texto("Essa reserva já é sua."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "Reserve a quadra para 2030-03-09."}
    )

    assert resposta.status_code == 200
    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    assert reservas == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]

    resultado = _resultado_da_tool(
        (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json(), "reservar_area"
    )
    assert resultado["motivo"] == "ja_e_sua"
    assert "já é sua" in resultado["mensagem"]


async def test_area_inexistente_nomeia_as_tres_areas(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("reservar_area", area="piscina", data="2030-04-06"),
            texto("Não temos piscina reservável."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "Reserve a piscina para 2030-04-06."}
    )

    assert resposta.status_code == 200
    with bancada.conexao() as conexao:
        assert conexao.execute(
            "SELECT count(*) FROM reservas WHERE area = 'piscina'"
        ).fetchone()[0] == 0

    resultado = _resultado_da_tool(
        (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json(), "reservar_area"
    )
    for nome in ("Salão de festas", "Churrasqueira", "Quadra poliesportiva"):
        assert nome in resultado["mensagem"]


async def test_cancelar_reserva_alheia_e_inexistente_respondem_igual(
    bancada: Bancada,
) -> None:
    sessao = await criar_sessao(bancada, "101")

    async def cancelar(area: str, data: str) -> dict:
        bancada.roteirizar(
            assistente_aurora=[transferir("especialista_reservas")],
            especialista_reservas=[
                chamar("cancelar_reserva", area=area, data=data),
                texto("Não encontrei essa reserva."),
            ],
        )
        await bancada.cliente.post(
            f"/sessoes/{sessao}/mensagens",
            json={"texto": f"Cancele {area} em {data}."},
        )
        eventos = (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json()
        return _resultado_da_tool(eventos, "cancelar_reserva", ultima=True)

    alheia = await cancelar("salao-de-festas", "2030-03-16")
    inexistente = await cancelar("salao-de-festas", "2031-12-31")

    assert alheia["motivo"] == inexistente["motivo"] == "sem_reserva_sua"
    assert alheia["mensagem"].replace("2030-03-16", "D") == inexistente[
        "mensagem"
    ].replace("2031-12-31", "D")

    assert (await bancada.cliente.get("/apartamentos/302/reservas")).json() == [
        {"codigo": "RSV-4821", "area": "salao-de-festas", "data": "2030-03-16"}
    ]
    eventos = json.dumps(
        (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json(),
        ensure_ascii=False,
    )
    assert "RSV-4821" not in eventos


async def test_duas_aprovacoes_simultaneas_somam_uma_reserva(bancada: Bancada) -> None:
    """O passo 14: 101 e 201 aprovam a mesma área e data ao mesmo tempo.

    As duas pendências existem antes do disparo, então o que corre em paralelo é
    exatamente a gravação — não a conversa que levou até ela.
    """
    s3 = await criar_sessao(bancada, "101")
    s4 = await criar_sessao(bancada, "201")

    pendencias = {}
    for sessao in (s3, s4):
        bancada.roteirizar(
            assistente_aurora=[transferir("especialista_reservas")],
            especialista_reservas=[
                chamar("reservar_area", area="salao-de-festas", data="2030-05-11")
            ],
        )
        resposta = await bancada.cliente.post(
            f"/sessoes/{sessao}/mensagens",
            json={"texto": "Reserve o salão de festas para 2030-05-11."},
        )
        pendencias[sessao] = resposta.json()["confirmacoes_pendentes"][0]["id"]

    bancada.roteirizar(
        especialista_reservas=[
            texto("Pronto."),
            texto("Pronto."),
            texto("Pronto."),
            texto("Pronto."),
        ]
    )
    aprovacoes = await asyncio.gather(
        *(
            bancada.cliente.post(
                f"/sessoes/{sessao}/confirmacoes",
                json={"id": identificador, "confirmado": True},
            )
            for sessao, identificador in pendencias.items()
        )
    )

    assert [a.status_code for a in aprovacoes] == [200, 200]
    assert all(a.status_code < 500 for a in aprovacoes)

    do_101 = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    do_201 = (await bancada.cliente.get("/apartamentos/201/reservas")).json()
    do_salao = [
        r
        for r in do_101 + do_201
        if r["area"] == "salao-de-festas" and r["data"] == "2030-05-11"
    ]
    assert len(do_salao) == 1


def _resultado_da_tool(eventos: list[dict], nome: str, ultima: bool = False) -> dict:
    respostas = [
        parte["functionResponse"]["response"]
        for evento in eventos
        for parte in (evento.get("content") or {}).get("parts", [])
        if parte.get("functionResponse", {}).get("name") == nome
    ]
    assert respostas, f"nenhuma resposta da tool {nome} nos eventos"
    return respostas[-1] if ultima else respostas[0]
