"""C13, C28 — nada se perde no reinício, nem os eventos nem uma pendência aberta.

`bancada.reiniciar()` joga fora a montagem inteira — serviço de sessão, Runner,
agentes — e remonta sobre os mesmos arquivos. O que continuar valendo depois disso
não pode ter vindo da memória do processo anterior.
"""

from __future__ import annotations

from testes.fio.conftest import criar_sessao
from testes.fio.modelo import chamar, texto, transferir
from testes.fio.servidor import Bancada


async def test_reinicio_preserva_os_eventos_e_aceita_nova_mensagem(
    bancada: Bancada,
) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("reservar_area", area="quadra", data="2030-04-06"),
            texto("Quadra reservada para 2030-04-06."),
        ],
    )
    await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "Reserve a quadra para 2030-04-06."}
    )

    antes = (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json()
    assert len(antes) >= 5

    await bancada.reiniciar()

    depois = (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json()
    assert len(depois) == len(antes)
    assert depois == antes

    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("listar_minhas_reservas"),
            texto("Quadra em 2030-03-09 e em 2030-04-06."),
        ],
    )
    nova = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "Quais são as minhas reservas agora?"}
    )
    assert nova.status_code == 200

    final = (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json()
    assert len(final) > len(antes)
    assert final[: len(antes)] == antes

    # O que foi gravado antes do reinício continua valendo.
    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    assert {r["data"] for r in reservas} == {"2030-03-09", "2030-04-06"}


async def test_pendencia_aprovada_depois_do_reinicio_executa(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
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
    pendente = pedido.json()["confirmacoes_pendentes"][0]["id"]

    await bancada.reiniciar()

    # A pendência continua listada: ela é derivada dos eventos em disco, não de
    # estado em memória do processo que a criou.
    bancada.roteirizar(especialista_reservas=[texto("Salão reservado.")])
    aprovacao = await bancada.cliente.post(
        f"/sessoes/{sessao}/confirmacoes", json={"id": pendente, "confirmado": True}
    )

    assert aprovacao.status_code == 200
    assert aprovacao.json()["confirmacoes_pendentes"] == []

    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    do_salao = [
        r
        for r in reservas
        if r["area"] == "salao-de-festas" and r["data"] == "2030-04-20"
    ]
    assert len(do_salao) == 1
