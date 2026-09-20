"""Um modelo roteirizado no lugar do Gemini.

As garantias do desafio são afirmações sobre o que o código permite, não sobre o
que o modelo resolve escrever. Um modelo roteirizado prova isso melhor do que uma
chamada real: ele pode tentar exatamente o que um morador de má-fé tentaria —
pedir a tool com o apartamento do vizinho, dizer que já confirmou, mandar gravar
duas vezes — e a prova mostra que o código recusa, sempre, sem depender de sorte.

O que depende do texto do Gemini de verdade fica no roteiro do avaliador.
"""

from __future__ import annotations

import re
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

NOME_INTERNO = re.compile(r'Your internal name is "([^"]+)"')


def texto(conteudo: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=conteudo)]),
        turn_complete=True,
    )


def chamar(__tool: str, **argumentos) -> LlmResponse:
    """Um turno em que o modelo chama uma tool.

    O nome do parâmetro é posicional-only para que `chamar("autorizar_visitante",
    nome=...)` não colida com ele.
    """
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name=__tool, args=dict(argumentos)
                    )
                )
            ],
        ),
        turn_complete=True,
    )


def transferir(agente: str) -> LlmResponse:
    return chamar("transfer_to_agent", agent_name=agente)


class ModeloRoteirizado(BaseLlm):
    """Devolve, por agente, as respostas que o teste escreveu, na ordem.

    O agente é identificado pela instrução de identidade que o próprio ADK injeta
    (`flows/llm_flows/identity.py`), então o roteiro é escrito em termos de quem
    responde — que é como o desenho da árvore de agentes é discutido.
    """

    model: str = "modelo-roteirizado"
    roteiro: dict[str, list[LlmResponse]] = {}
    chamadas: list[tuple[str, str]] = []

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["modelo-roteirizado"]

    def _agente(self, llm_request: LlmRequest) -> str:
        instrucao = ""
        config = getattr(llm_request, "config", None)
        if config is not None and config.system_instruction:
            instrucao = str(config.system_instruction)
        encontrado = NOME_INTERNO.search(instrucao)
        return encontrado.group(1) if encontrado else "desconhecido"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        agente = self._agente(llm_request)
        restantes = self.roteiro.get(agente)
        if restantes:
            resposta = restantes.pop(0)
        else:
            # Sem roteiro sobrando o agente encerra com uma frase neutra, para que
            # um roteiro incompleto vire uma asserção falhando e não um travamento.
            resposta = texto(f"[{agente} sem roteiro]")
        self.chamadas.append((agente, _resumo(resposta)))
        yield resposta


def _resumo(resposta: LlmResponse) -> str:
    partes = (resposta.content.parts if resposta.content else None) or []
    for parte in partes:
        if parte.function_call:
            return f"call:{parte.function_call.name}"
    return "texto"


def roteirizar(**por_agente: list[LlmResponse]) -> ModeloRoteirizado:
    return ModeloRoteirizado(
        roteiro={agente: list(turnos) for agente, turnos in por_agente.items()},
        chamadas=[],
    )
