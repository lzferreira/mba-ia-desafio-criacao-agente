"""C17, C45, C46, C48, C49 — o regulamento é consultado e não entra na sessão.

A prova decisiva é a do vazamento: o especialista lê de propósito dois capítulos
de outros assuntos antes de achar o certo, e nem assim o texto deles chega aos
eventos do morador. É o `AgentTool` que isola — se o Regulamento fosse sub-agente,
esses capítulos estariam na sessão, e a asserção falharia.
"""

from __future__ import annotations

import json

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from testes.fio.conftest import criar_sessao
from testes.fio.modelo import chamar, texto, transferir
from testes.fio.servidor import RAIZ_DO_PROJETO, Bancada

PERGUNTA_DA_PISCINA = "Até que horas a piscina funciona aos domingos?"
RESPOSTA_DA_PISCINA = (
    "Aos domingos e feriados a piscina funciona das 9h às 20h, pelo Art. 22, II."
)
SENTINELA_DO_VIII = "coleira refletiva cor de mostarda"
SENTINELA_DO_XI = "dez quilômetros por hora"


def texto_e_chamada(conteudo: str, tool: str, **argumentos) -> LlmResponse:
    """Um turno em que o modelo fala e chama uma tool na mesma resposta."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(text=conteudo),
                types.Part(
                    function_call=types.FunctionCall(name=tool, args=dict(argumentos))
                ),
            ],
        ),
        turn_complete=True,
    )


async def eventos_em_texto(bancada: Bancada, sessao: str) -> str:
    eventos = (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json()
    return json.dumps(eventos, ensure_ascii=False)


def roteiro_da_piscina(bancada: Bancada, procurar_em_outros_capitulos: bool) -> None:
    turnos_do_especialista = []
    if procurar_em_outros_capitulos:
        turnos_do_especialista += [
            chamar("ler_capitulo_do_regulamento", capitulo="VIII"),
            chamar("ler_capitulo_do_regulamento", capitulo="XI"),
        ]
    turnos_do_especialista += [
        chamar("ler_capitulo_do_regulamento", capitulo="IV"),
        texto(RESPOSTA_DA_PISCINA),
    ]
    bancada.roteirizar(
        assistente_aurora=[
            chamar("especialista_regulamento", request=PERGUNTA_DA_PISCINA),
            texto(RESPOSTA_DA_PISCINA),
        ],
        especialista_regulamento=turnos_do_especialista,
    )


async def test_especialista_e_acionado_como_tool_sem_transferencia(
    bancada: Bancada,
) -> None:
    sessao = await criar_sessao(bancada, "101")
    roteiro_da_piscina(bancada, procurar_em_outros_capitulos=False)
    await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": PERGUNTA_DA_PISCINA}
    )

    eventos = (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json()
    chamadas = [
        parte["functionCall"]
        for evento in eventos
        for parte in (evento.get("content") or {}).get("parts", [])
        if "functionCall" in parte
    ]

    nomes = [c["name"] for c in chamadas]
    assert "especialista_regulamento" in nomes
    # Nenhuma transferência para ele: ele roda como tool, na sessão descartável.
    transferencias = [
        c["args"].get("agent_name") for c in chamadas if c["name"] == "transfer_to_agent"
    ]
    assert "especialista_regulamento" not in transferencias

    autores = {evento["author"] for evento in eventos}
    assert "especialista_regulamento" not in autores


async def test_resposta_sobre_a_piscina_chega_ao_morador_com_20h(
    bancada_realista: Bancada,
) -> None:
    """O `20h` vem do arquivo, não do teste.

    Esta prova roda com o modelo que decide pelo texto: ninguém alimenta a frase
    que vai ser asseverada. O horário só pode ter chegado à resposta por
    `ler_capitulo_do_regulamento`, que leu o Capítulo IV de `dados/regulamento.md`.
    """
    sessao = await criar_sessao(bancada_realista, "101")

    resposta = await bancada_realista.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": PERGUNTA_DA_PISCINA}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()["resposta"]
    assert "20h" in corpo, corpo
    assert "domingos" in corpo.lower(), corpo

    # E o horário asseverado é mesmo o que está no arquivo, no Art. 22, II.
    fonte = (RAIZ_DO_PROJETO / "dados" / "regulamento.md").read_text("utf-8")
    assert "Aos domingos e feriados, a piscina funciona das 9h às 20h" in fonte


async def test_nenhum_evento_contem_capitulo_de_outro_assunto(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    # O especialista erra dois capítulos antes de acertar: se o isolamento não
    # existisse, o texto dos dois estaria nos eventos abaixo.
    roteiro_da_piscina(bancada, procurar_em_outros_capitulos=True)

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": PERGUNTA_DA_PISCINA}
    )
    assert "20h" in resposta.json()["resposta"]

    # Sem isto a prova seria vazia: se o especialista nunca rodasse, os capítulos
    # de outros assuntos não estariam nos eventos por não terem sido lidos, e não
    # por estarem isolados. Os três turnos dele foram consumidos, nesta ordem.
    do_especialista = [
        resumo
        for agente, resumo in bancada.modelo.chamadas
        if agente == "especialista_regulamento"
    ]
    assert do_especialista == [
        "call:ler_capitulo_do_regulamento",
        "call:ler_capitulo_do_regulamento",
        "call:ler_capitulo_do_regulamento",
        "texto",
    ]

    eventos = await eventos_em_texto(bancada, sessao)
    assert SENTINELA_DO_VIII not in eventos
    assert SENTINELA_DO_XI not in eventos
    assert "Animais de estimação" not in eventos
    assert "Garagem e veículos" not in eventos

    # E nem o capítulo certo entra inteiro: o que volta é a resposta.
    assert "Art. 21" not in eventos
    assert "exame dermatológico" not in eventos


async def test_pergunta_fora_do_regulamento_diz_que_nao_consta(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    pergunta = "O condomínio empresta guarda-chuva na portaria?"
    bancada.roteirizar(
        assistente_aurora=[
            chamar("especialista_regulamento", request=pergunta),
            texto("Isso não consta no regulamento interno."),
        ],
        especialista_regulamento=[
            chamar("listar_capitulos_do_regulamento"),
            texto("Isso não consta no regulamento interno."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": pergunta}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()["resposta"]
    assert "não consta" in corpo.lower()
    assert "Art." not in corpo

    # O índice de capítulos não traz artigo nenhum para os eventos.
    eventos = await eventos_em_texto(bancada, sessao)
    assert "Art. " not in eventos


async def test_mensagem_mista_passa_pelos_dois_especialistas(bancada: Bancada) -> None:
    sessao = await criar_sessao(bancada, "101")
    bancada.roteirizar(
        assistente_aurora=[
            chamar("especialista_regulamento", request=PERGUNTA_DA_PISCINA),
            texto_e_chamada(
                "Aos domingos a piscina fecha às 20h. Vou cuidar da reserva.",
                "transfer_to_agent",
                agent_name="especialista_reservas",
            ),
        ],
        especialista_regulamento=[
            chamar("ler_capitulo_do_regulamento", capitulo="IV"),
            texto(RESPOSTA_DA_PISCINA),
        ],
        especialista_reservas=[
            chamar("reservar_area", area="quadra", data="2030-04-06"),
            texto("Quadra reservada para 2030-04-06."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens",
        json={
            "texto": f"{PERGUNTA_DA_PISCINA} E reserve a quadra para 2030-04-06."
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()["resposta"]
    assert "20h" in corpo
    assert "2030-04-06" in corpo

    # A parte da reserva não é encenação: a linha existe no banco.
    with bancada.conexao() as conexao:
        assert conexao.execute(
            "SELECT count(*) FROM reservas"
            " WHERE area = 'quadra' AND data = '2030-04-06' AND ativa = 1"
        ).fetchone()[0] == 1

    eventos = (await bancada.cliente.get(f"/sessoes/{sessao}/eventos")).json()
    chamadas = [
        parte["functionCall"]["name"]
        for evento in eventos
        for parte in (evento.get("content") or {}).get("parts", [])
        if "functionCall" in parte
    ]
    assert "especialista_regulamento" in chamadas
    assert "transfer_to_agent" in chamadas
    assert "reservar_area" in chamadas

    reservas = (await bancada.cliente.get("/apartamentos/101/reservas")).json()
    assert [r for r in reservas if r["data"] == "2030-04-06"] != []


async def test_pergunta_que_atravessa_capitulos_le_os_pertinentes(
    bancada: Bancada,
) -> None:
    """Estado do design que nenhum critério numerou, provado assim mesmo.

    Um capítulo pertinente não é "outro assunto": ler dois de propósito, quando a
    pergunta atravessa os dois, continua dentro da Garantia 4 — o que não pode é
    o texto deles sair da sessão descartável do `AgentTool`.
    """
    sessao = await criar_sessao(bancada, "101")
    pergunta = "Posso levar meu cachorro até a garagem para embarcar no carro?"
    bancada.roteirizar(
        assistente_aurora=[
            chamar("especialista_regulamento", request=pergunta),
            texto("Sim, conduzido por guia, e a pé até o veículo."),
        ],
        especialista_regulamento=[
            chamar("ler_capitulo_do_regulamento", capitulo="VIII"),
            chamar("ler_capitulo_do_regulamento", capitulo="XI"),
            texto("Sim, conduzido por guia, e a pé até o veículo."),
        ],
    )

    resposta = await bancada.cliente.post(
        f"/sessoes/{sessao}/mensagens", json={"texto": pergunta}
    )

    assert resposta.status_code == 200
    lidos = [
        resumo
        for agente, resumo in bancada.modelo.chamadas
        if agente == "especialista_regulamento"
    ]
    assert lidos.count("call:ler_capitulo_do_regulamento") == 2

    eventos = await eventos_em_texto(bancada, sessao)
    assert SENTINELA_DO_VIII not in eventos
    assert SENTINELA_DO_XI not in eventos
