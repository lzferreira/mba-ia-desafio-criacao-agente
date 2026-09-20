"""A retomada da confirmação precisa chegar ao agente que a pediu.

O enunciado chama isso de armadilha mais cara do desafio, e é silenciosa: a rota
responde 200, nenhum erro aparece e a ação não executa. Quem escolhe o agente é
`find_agent_to_run`, e estas provas fixam exatamente o que ele faz com a nossa
árvore — inclusive o caso em que a escolha certa deixa de ser acidental.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.agents._agent_router import find_agent_to_run
from google.adk.apps import ResumabilityConfig
from google.adk.events import Event
from google.adk.sessions import Session
from google.genai import types

from assistente import armazenamento
from assistente.agentes import construir_agentes
from assistente.aplicacao import Aplicacao, construir_api
from assistente.configuracao import Configuracao
from assistente.pendencias import NOME_DA_CONFIRMACAO
from testes.conftest import RAIZ

ID_DA_CONFIRMACAO = "adk-confirmacao-1"
ID_DA_CHAMADA = "adk-reserva-1"


def _aplicacao(tmp_path: Path) -> Aplicacao:
    condominio = tmp_path / "condominio.db"
    armazenamento.restaurar(condominio, tmp_path / "sessoes.db", RAIZ / "dados")
    return Aplicacao(
        configuracao=Configuracao(
            banco_do_condominio=condominio,
            banco_de_sessoes=tmp_path / "sessoes.db",
            diretorio_de_dados=RAIZ / "dados",
            fabrica_de_modelo=lambda: "modelo-de-teste",
        )
    )


def _sessao_com_confirmacao_pendente(autor: str) -> Session:
    """Uma sessão parada no ponto exato: o especialista pediu, o morador respondeu."""
    pedido = Event(
        author=autor,
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name=NOME_DA_CONFIRMACAO,
                        id=ID_DA_CONFIRMACAO,
                        args={
                            "originalFunctionCall": {
                                "id": ID_DA_CHAMADA,
                                "name": "reservar_area",
                                "args": {
                                    "area": "salao-de-festas",
                                    "data": "2030-04-20",
                                },
                            }
                        },
                    )
                )
            ],
        ),
        long_running_tool_ids={ID_DA_CONFIRMACAO},
    )
    resposta = Event(
        author="user",
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=ID_DA_CONFIRMACAO,
                        name=NOME_DA_CONFIRMACAO,
                        response={"confirmed": True},
                    )
                )
            ],
        ),
    )
    return Session(
        id="sessao-de-teste",
        app_name="aurora",
        user_id="morador",
        state={"apartamento": "101"},
        events=[pedido, resposta],
    )


def test_a_aplicacao_sobe_com_a_retomada_ligada(tmp_path: Path) -> None:
    """A linha precisa continuar lá: é a única que torna a escolha não-acidental.

    Sem esta asserção, trocar `is_resumable` para `False` não quebraria prova
    nenhuma — a árvore de hoje esconde a diferença (ver o teste seguinte).
    """
    api = construir_api(_aplicacao(tmp_path).configuracao)

    # O Runner guarda o App que recebeu; é dele que sai a configuração efetiva.
    configurada = api.state.aplicacao.runner.app.resumability_config
    assert configurada is not None, "o App subiu sem ResumabilityConfig"
    assert configurada.is_resumable is True


def test_com_a_retomada_ligada_a_resposta_vai_ao_autor_da_confirmacao(
    tmp_path: Path,
) -> None:
    principal = construir_agentes(_aplicacao(tmp_path))
    sessao = _sessao_com_confirmacao_pendente("especialista_reservas")

    escolhido = find_agent_to_run(
        sessao, principal, ResumabilityConfig(is_resumable=True)
    )

    assert escolhido.name == "especialista_reservas"


def test_sem_a_retomada_a_escolha_certa_depende_de_o_especialista_poder_transferir(
    tmp_path: Path,
) -> None:
    """O que a linha compra, demonstrado nos dois sentidos.

    Com a transferência liberada — a árvore que entregamos — o desligado também
    acerta, por acidente: o especialista foi quem respondeu por último e é
    transferível, então a varredura de eventos cai nele de qualquer jeito.

    Basta alguém bloquear a transferência de volta ao pai, uma mudança plausível
    de endurecimento, e o desligado passa a devolver o agente raiz. Aí a
    confirmação é abandonada em silêncio, que é a falha que o enunciado nomeia.
    """
    principal = construir_agentes(_aplicacao(tmp_path))
    sessao = _sessao_com_confirmacao_pendente("especialista_reservas")
    desligado = ResumabilityConfig(is_resumable=False)

    # Árvore como entregamos: o desligado acerta sem mérito próprio.
    assert find_agent_to_run(sessao, principal, desligado).name == (
        "especialista_reservas"
    )

    especialista = next(
        sub for sub in principal.sub_agents if sub.name == "especialista_reservas"
    )
    especialista.disallow_transfer_to_parent = True

    assert find_agent_to_run(sessao, principal, desligado).name == principal.name
    assert find_agent_to_run(
        sessao, principal, ResumabilityConfig(is_resumable=True)
    ).name == "especialista_reservas"


def test_confirmacao_de_agente_desconhecido_cai_na_raiz(tmp_path: Path) -> None:
    """Autor que não existe na árvore não derruba o roteamento."""
    principal = construir_agentes(_aplicacao(tmp_path))
    sessao = _sessao_com_confirmacao_pendente("agente_que_nao_existe")

    escolhido = find_agent_to_run(
        sessao, principal, ResumabilityConfig(is_resumable=True)
    )

    assert escolhido.name == principal.name
