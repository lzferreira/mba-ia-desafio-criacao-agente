"""C13, C28 no nível que os critérios pedem: a API parada e subida de novo.

Os critérios 13 e 28 dizem "a API é parada e sobe de novo com o mesmo comando" e
"a API é reiniciada". Uma remontagem em processo descarta os objetos, mas o
processo continua vivo — e é justamente entre dois processos que a retomada da
confirmação tem histórico de falhar em silêncio, segundo o próprio enunciado.

Aqui o processo morre de verdade, com uma pendência aberta, e a aprovação chega
ao processo novo.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from testes.conftest import BASE_DO_CONTRATO, ApiDeVerdade, porta_livre

pytestmark = pytest.mark.contrato

MODULO_DE_BANCADA = "testes.fio.api_de_bancada"


def _cliente() -> httpx.Client:
    return httpx.Client(base_url=BASE_DO_CONTRATO, timeout=60.0)


def test_pendencia_aprovada_depois_de_reiniciar_o_processo_executa(
    raiz_isolada: Path,
) -> None:
    if not porta_livre():
        pytest.skip("a porta 8000 do contrato está ocupada por outro processo")

    api = ApiDeVerdade(raiz_isolada, modulo=MODULO_DE_BANCADA)
    api.subir()
    try:
        with _cliente() as cliente:
            sessao = cliente.post("/sessoes", json={"apartamento": "101"}).json()[
                "session_id"
            ]
            pedido = cliente.post(
                f"/sessoes/{sessao}/mensagens",
                json={"texto": "Reserve o salão de festas para 2030-04-20."},
            )
            assert pedido.status_code == 200
            pendentes = pedido.json()["confirmacoes_pendentes"]
            assert len(pendentes) == 1, pedido.json()
            pendencia = pendentes[0]["id"]
            eventos_antes = len(cliente.get(f"/sessoes/{sessao}/eventos").json())
            assert _do_salao(cliente, "101") == []
    finally:
        api.parar()

    # O processo morreu. Nada do Runner, do serviço de sessão ou da pendência
    # sobreviveu em memória.
    api = ApiDeVerdade(raiz_isolada, modulo=MODULO_DE_BANCADA)
    api.subir()
    try:
        with _cliente() as cliente:
            eventos = cliente.get(f"/sessoes/{sessao}/eventos")
            assert eventos.status_code == 200
            assert len(eventos.json()) == eventos_antes

            aprovacao = cliente.post(
                f"/sessoes/{sessao}/confirmacoes",
                json={"id": pendencia, "confirmado": True},
            )
            assert aprovacao.status_code == 200, aprovacao.text
            assert aprovacao.json()["confirmacoes_pendentes"] == []

            # A retomada chegou ao agente que pediu a confirmação e a tool
            # executou: sem isso a rota responderia 200 do mesmo jeito e a
            # reserva não existiria — a falha silenciosa do enunciado.
            assert len(_do_salao(cliente, "101")) == 1

            repetida = cliente.post(
                f"/sessoes/{sessao}/confirmacoes",
                json={"id": pendencia, "confirmado": True},
            )
            assert repetida.status_code == 409
            assert len(_do_salao(cliente, "101")) == 1
    finally:
        api.parar()


def test_eventos_e_dados_sobrevivem_ao_reinicio_do_processo(raiz_isolada: Path) -> None:
    if not porta_livre():
        pytest.skip("a porta 8000 do contrato está ocupada por outro processo")

    api = ApiDeVerdade(raiz_isolada, modulo=MODULO_DE_BANCADA)
    api.subir()
    try:
        with _cliente() as cliente:
            sessao = cliente.post("/sessoes", json={"apartamento": "101"}).json()[
                "session_id"
            ]
            cliente.post(
                f"/sessoes/{sessao}/mensagens",
                json={"texto": "Reserve a quadra para 2030-04-06."},
            )
            antes = cliente.get(f"/sessoes/{sessao}/eventos").json()
            assert len(antes) >= 5
    finally:
        api.parar()

    api = ApiDeVerdade(raiz_isolada, modulo=MODULO_DE_BANCADA)
    api.subir()
    try:
        with _cliente() as cliente:
            depois = cliente.get(f"/sessoes/{sessao}/eventos").json()
            assert len(depois) == len(antes)
            assert depois == antes

            nova = cliente.post(
                f"/sessoes/{sessao}/mensagens",
                json={"texto": "Quais são as minhas reservas agora?"},
            )
            assert nova.status_code == 200
            final = cliente.get(f"/sessoes/{sessao}/eventos").json()
            assert len(final) > len(antes)
            assert final[: len(antes)] == antes

            reservas = cliente.get("/apartamentos/101/reservas").json()
            assert {r["data"] for r in reservas} == {"2030-03-09", "2030-04-06"}
    finally:
        api.parar()


def _do_salao(cliente: httpx.Client, apartamento: str) -> list[dict]:
    reservas = cliente.get(f"/apartamentos/{apartamento}/reservas").json()
    return [
        r
        for r in reservas
        if r["area"] == "salao-de-festas" and r["data"] == "2030-04-20"
    ]
