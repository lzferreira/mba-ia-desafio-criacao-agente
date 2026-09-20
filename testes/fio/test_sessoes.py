"""C9 a C12 — criação da sessão, rota de eventos e os 404 do contrato."""

from __future__ import annotations

from testes.fio.conftest import criar_sessao
from testes.fio.modelo import chamar, texto, transferir
from testes.fio.servidor import Bancada


async def test_criacao_grava_o_apartamento_no_state_persistido(bancada: Bancada) -> None:
    resposta = await bancada.cliente.post("/sessoes", json={"apartamento": "101"})

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert list(corpo) == ["session_id"]
    assert isinstance(corpo["session_id"], str) and corpo["session_id"]

    # Lido de um serviço de sessão recém-aberto sobre o arquivo: o apartamento
    # está no disco, não na memória de quem atendeu a requisição.
    assert await bancada.estado_persistido(corpo["session_id"]) == {
        "apartamento": "101"
    }


async def test_apartamento_inexistente_devolve_404_e_nao_cria_sessao(
    bancada: Bancada,
) -> None:
    resposta = await bancada.cliente.post("/sessoes", json={"apartamento": "999"})

    assert resposta.status_code == 404
    assert _nenhuma_sessao(bancada), "a recusa não pode deixar sessão gravada"


def _nenhuma_sessao(bancada: Bancada) -> bool:
    import sqlite3

    if not bancada.banco_de_sessoes.exists():
        return True
    conexao = sqlite3.connect(bancada.banco_de_sessoes)
    try:
        tabelas = [
            linha[0]
            for linha in conexao.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ]
        if "sessions" not in tabelas:
            return True
        return conexao.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    finally:
        conexao.close()


async def test_eventos_trazem_function_call_e_function_response_em_ordem(
    bancada: Bancada,
) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[transferir("especialista_reservas")],
        especialista_reservas=[
            chamar("listar_minhas_reservas"),
            texto("Você tem a quadra em 2030-03-09."),
        ],
    )
    await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": "Quais são as minhas reservas?"}
    )

    resposta = await bancada.cliente.get(f"/sessoes/{sessao}/eventos")
    assert resposta.status_code == 200
    eventos = resposta.json()

    # Ordem cronológica: os timestamps não retrocedem.
    marcas = [e["timestamp"] for e in eventos]
    assert marcas == sorted(marcas)

    chamadas = [
        parte["functionCall"]["name"]
        for evento in eventos
        for parte in (evento.get("content") or {}).get("parts", [])
        if "functionCall" in parte
    ]
    respostas = [
        parte["functionResponse"]["name"]
        for evento in eventos
        for parte in (evento.get("content") or {}).get("parts", [])
        if "functionResponse" in parte
    ]
    assert "transfer_to_agent" in chamadas
    assert "listar_minhas_reservas" in chamadas
    assert "listar_minhas_reservas" in respostas

    # Conteúdo completo: a resposta da tool vem inteira, não resumida.
    corpo_da_tool = [
        parte["functionResponse"]["response"]
        for evento in eventos
        for parte in (evento.get("content") or {}).get("parts", [])
        if parte.get("functionResponse", {}).get("name") == "listar_minhas_reservas"
    ]
    assert corpo_da_tool[0]["reservas"] == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]


async def test_sessao_inexistente_devolve_404_nas_tres_rotas(bancada: Bancada) -> None:
    eventos = await bancada.cliente.get("/sessoes/sessao-inexistente/eventos")
    mensagem = await bancada.cliente.post(
        "/sessoes/sessao-inexistente/mensagens", json={"texto": "oi"}
    )
    confirmacao = await bancada.cliente.post(
        "/sessoes/sessao-inexistente/confirmacoes",
        json={"id": "qualquer", "confirmado": True},
    )

    assert eventos.status_code == 404
    assert mensagem.status_code == 404
    assert confirmacao.status_code == 404
    # Nada foi executado: o modelo não chegou a ser chamado nenhuma vez.
    assert bancada.modelo.chamadas == []
