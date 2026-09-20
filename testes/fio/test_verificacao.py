"""C4 — as rotas de verificação leem os dados direto, sem passar pelo modelo."""

from __future__ import annotations

from testes.fio.servidor import Bancada


async def test_rotas_de_verificacao_devolvem_os_dados_iniciais(bancada: Bancada) -> None:
    reservas = await bancada.cliente.get("/apartamentos/101/reservas")
    visitantes = await bancada.cliente.get("/apartamentos/302/visitantes")

    assert reservas.status_code == 200
    assert reservas.json() == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]
    assert visitantes.status_code == 200
    assert visitantes.json() == [{"nome": "Marina Duarte", "data": "2030-03-16"}]

    # Sem modelo no caminho: nenhuma chamada foi feita para responder isto.
    assert bancada.modelo.chamadas == []


async def test_apartamento_sem_nada_devolve_lista_vazia(bancada: Bancada) -> None:
    vazio = await bancada.cliente.get("/apartamentos/102/reservas")
    assert vazio.status_code == 200
    assert vazio.json() == []

    inexistente = await bancada.cliente.get("/apartamentos/999/visitantes")
    assert inexistente.status_code == 200
    assert inexistente.json() == []
