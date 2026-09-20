"""Pendências de confirmação derivadas dos eventos da sessão.

Não existe tabela de pendências. Uma confirmação está pendente quando existe uma
`functionCall` `adk_request_confirmation` de id X sem nenhuma `functionResponse` de
id X nos eventos. Isso dá de graça as três coisas que a Garantia 1 pede: o `409`
de um id já respondido (ele deixou de estar pendente no instante em que a resposta
virou evento), a execução única, e a sobrevivência ao reinício — porque os eventos
estão em SQLite e não na memória do processo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from google.genai import types

NOME_DA_CONFIRMACAO = "adk_request_confirmation"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pendencia:
    id: str
    acao: str
    detalhes: dict[str, Any]
    chamada_original: str | None

    def como_json(self) -> dict[str, Any]:
        return {"id": self.id, "acao": self.acao, "detalhes": self.detalhes}


def _chamada_original(argumentos: Any) -> dict[str, Any]:
    if isinstance(argumentos, dict):
        original = argumentos.get("originalFunctionCall")
        if isinstance(original, dict):
            return original
    return {}


def derivar(eventos: Iterable[Any]) -> list[Pendencia]:
    """Lista, em ordem, as confirmações desta sessão que ainda não foram respondidas."""
    eventos = list(eventos)
    respondidos = {
        resposta.id
        for evento in eventos
        for resposta in evento.get_function_responses()
        if resposta.id
    }

    pendentes: list[Pendencia] = []
    for evento in eventos:
        for chamada in evento.get_function_calls():
            if chamada.name != NOME_DA_CONFIRMACAO or not chamada.id:
                continue
            if chamada.id in respondidos:
                continue
            original = _chamada_original(chamada.args)
            argumentos = original.get("args")
            pendentes.append(
                Pendencia(
                    id=chamada.id,
                    acao=original.get("name") or NOME_DA_CONFIRMACAO,
                    detalhes=argumentos if isinstance(argumentos, dict) else {},
                    chamada_original=original.get("id"),
                )
            )
    return pendentes


def encontrar(eventos: Iterable[Any], identificador: str) -> Pendencia | None:
    for pendencia in derivar(eventos):
        if pendencia.id == identificador:
            return pendencia
    return None


def resposta_de_confirmacao(identificador: str, confirmado: bool) -> types.Content:
    """Monta a mensagem de usuário com que o ADK retoma a execução.

    É o mesmo formato que o cliente do `adk web` envia: uma `functionResponse` de
    nome `adk_request_confirmation`, com o id da pendência e um `ToolConfirmation`
    no corpo (`flows/llm_flows/request_confirmation.py:262-277`).
    """
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=identificador,
                    name=NOME_DA_CONFIRMACAO,
                    response={"confirmed": confirmado},
                )
            )
        ],
    )


def conferir_retomada(
    pendencia: Pendencia, eventos_da_retomada: Sequence[Any], sessao: str
) -> None:
    """Deixa rastro quando a retomada aceita a resposta e não executa a tool.

    É a falha que o enunciado chama de mais cara, e é silenciosa: a rota responde
    200, nenhum erro aparece e a ação não acontece. Sem esta linha, C23, C28 e C41
    falhariam sem dizer onde.
    """
    if pendencia.chamada_original is None:
        return
    executou = any(
        resposta.id == pendencia.chamada_original
        for evento in eventos_da_retomada
        for resposta in evento.get_function_responses()
    )
    if not executou:
        logger.warning(
            "confirmação %s da sessão %s respondida, mas a chamada original %s"
            " não foi reexecutada: a retomada não chegou ao agente que pediu",
            pendencia.id,
            sessao,
            pendencia.chamada_original,
        )
