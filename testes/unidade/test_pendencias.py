"""A derivação de pendências, caso a caso.

`pendencias.derivar` decide sobre três estados de um id — pendente, já respondido,
inexistente — e é o que a rota de confirmações consulta antes de deixar qualquer
coisa chegar ao Runner. As provas de fio exercitam um caminho por vez; aqui a
tabela inteira é asseverada, inclusive as combinações que a conversa não produz
com facilidade.
"""

from __future__ import annotations

import logging

from google.adk.events import Event
from google.genai import types

from assistente import pendencias
from assistente.pendencias import NOME_DA_CONFIRMACAO


def pedido_de_confirmacao(
    identificador: str,
    chamada: str = "adk-original-1",
    tool: str = "reservar_area",
    autor: str = "especialista_reservas",
    **argumentos,
) -> Event:
    return Event(
        author=autor,
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name=NOME_DA_CONFIRMACAO,
                        id=identificador,
                        args={
                            "originalFunctionCall": {
                                "id": chamada,
                                "name": tool,
                                "args": dict(argumentos),
                            }
                        },
                    )
                )
            ],
        ),
        long_running_tool_ids={identificador},
    )


def resposta(identificador: str, nome: str = NOME_DA_CONFIRMACAO) -> Event:
    return Event(
        author="user",
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=identificador, name=nome, response={"confirmed": True}
                    )
                )
            ],
        ),
    )


def execucao_da_tool(chamada: str, tool: str = "reservar_area") -> Event:
    return Event(
        author="especialista_reservas",
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=chamada, name=tool, response={"ok": True}
                    )
                )
            ],
        ),
    )


def test_confirmacao_sem_resposta_esta_pendente() -> None:
    eventos = [
        pedido_de_confirmacao("c1", area="salao-de-festas", data="2030-04-20")
    ]

    derivadas = pendencias.derivar(eventos)

    assert len(derivadas) == 1
    assert derivadas[0].id == "c1"
    assert derivadas[0].acao == "reservar_area"
    assert derivadas[0].detalhes == {
        "area": "salao-de-festas",
        "data": "2030-04-20",
    }
    assert derivadas[0].chamada_original == "adk-original-1"
    assert derivadas[0].como_json() == {
        "id": "c1",
        "acao": "reservar_area",
        "detalhes": {"area": "salao-de-festas", "data": "2030-04-20"},
    }


def test_confirmacao_respondida_deixa_de_estar_pendente() -> None:
    eventos = [pedido_de_confirmacao("c1"), resposta("c1")]

    assert pendencias.derivar(eventos) == []
    assert pendencias.encontrar(eventos, "c1") is None


def test_id_que_nunca_existiu_nao_e_encontrado() -> None:
    eventos = [pedido_de_confirmacao("c1")]

    assert pendencias.encontrar(eventos, "c1") is not None
    assert pendencias.encontrar(eventos, "c2") is None
    assert pendencias.encontrar([], "c1") is None


def test_varias_pendencias_saem_na_ordem_dos_eventos() -> None:
    eventos = [
        pedido_de_confirmacao("c1", chamada="o1"),
        pedido_de_confirmacao("c2", chamada="o2", tool="autorizar_visitante"),
        pedido_de_confirmacao("c3", chamada="o3"),
        resposta("c2"),
    ]

    assert [p.id for p in pendencias.derivar(eventos)] == ["c1", "c3"]
    assert pendencias.encontrar(eventos, "c2") is None


def test_a_resposta_de_outra_chamada_nao_consome_a_pendencia() -> None:
    """Só a `functionResponse` com o id da confirmação a encerra.

    A tool original responde com o id dela, não com o da confirmação; se os dois
    fossem confundidos, a execução encerraria a pendência antes da aprovação.
    """
    eventos = [
        pedido_de_confirmacao("c1", chamada="o1"),
        execucao_da_tool("o1"),
    ]

    assert [p.id for p in pendencias.derivar(eventos)] == ["c1"]


def test_confirmacao_com_payload_malformado_nao_derruba_a_derivacao() -> None:
    sem_original = Event(
        author="especialista_reservas",
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name=NOME_DA_CONFIRMACAO, id="c1", args={}
                    )
                )
            ],
        ),
    )

    derivadas = pendencias.derivar([sem_original])

    assert len(derivadas) == 1
    assert derivadas[0].id == "c1"
    assert derivadas[0].acao == NOME_DA_CONFIRMACAO
    assert derivadas[0].detalhes == {}
    assert derivadas[0].chamada_original is None


def test_chamada_de_tool_comum_nao_vira_pendencia() -> None:
    comum = Event(
        author="especialista_reservas",
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="reservar_area", id="o1", args={"area": "quadra"}
                    )
                )
            ],
        ),
    )

    assert pendencias.derivar([comum]) == []


def test_resposta_de_confirmacao_monta_o_payload_que_o_adk_aceita() -> None:
    conteudo = pendencias.resposta_de_confirmacao("c1", True)

    assert conteudo.role == "user"
    assert len(conteudo.parts) == 1
    resposta_montada = conteudo.parts[0].function_response
    assert resposta_montada.id == "c1"
    assert resposta_montada.name == NOME_DA_CONFIRMACAO
    assert resposta_montada.response == {"confirmed": True}

    negada = pendencias.resposta_de_confirmacao("c1", False)
    assert negada.parts[0].function_response.response == {"confirmed": False}


def test_conferir_retomada_avisa_quando_a_tool_original_nao_executou(caplog) -> None:
    """A falha silenciosa que o enunciado chama de mais cara deixa rastro."""
    pendencia = pendencias.derivar([pedido_de_confirmacao("c1", chamada="o1")])[0]

    with caplog.at_level(logging.WARNING, logger="assistente.pendencias"):
        pendencias.conferir_retomada(pendencia, [], "sessao-1")

    assert "c1" in caplog.text
    assert "sessao-1" in caplog.text
    assert "o1" in caplog.text


def test_conferir_retomada_fica_calado_quando_a_tool_executou(caplog) -> None:
    pendencia = pendencias.derivar([pedido_de_confirmacao("c1", chamada="o1")])[0]

    with caplog.at_level(logging.WARNING, logger="assistente.pendencias"):
        pendencias.conferir_retomada(pendencia, [execucao_da_tool("o1")], "sessao-1")

    assert caplog.text == ""
