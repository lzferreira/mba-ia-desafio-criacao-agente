"""C47 — o agente principal não recebe o regulamento nas instruções.

E a topologia que sustenta a Garantia 4: Regulamento é `AgentTool` e não sub-agente.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from google.adk.tools.agent_tool import AgentTool

from assistente import armazenamento
from assistente.agentes import construir_agentes
from assistente.aplicacao import Aplicacao
from assistente.configuracao import Configuracao
from testes.conftest import RAIZ

REGULAMENTO = RAIZ / "dados" / "regulamento.md"


@pytest.fixture
def principal(tmp_path: Path):
    condominio = tmp_path / "condominio.db"
    armazenamento.restaurar(condominio, tmp_path / "sessoes.db", RAIZ / "dados")
    aplicacao = Aplicacao(
        configuracao=Configuracao(
            banco_do_condominio=condominio,
            banco_de_sessoes=tmp_path / "sessoes.db",
            diretorio_de_dados=RAIZ / "dados",
            fabrica_de_modelo=lambda: "modelo-de-teste",
        )
    )
    return construir_agentes(aplicacao)


def test_instrucao_do_principal_nao_contem_trecho_do_regulamento(principal) -> None:
    instrucao = f"{principal.instruction}\n{principal.description or ''}"

    substanciais = [
        linha.strip()
        for linha in REGULAMENTO.read_text(encoding="utf-8").splitlines()
        if len(linha.strip()) >= 40
    ]
    assert len(substanciais) > 200, "o regulamento deveria ter centenas de linhas longas"

    vazadas = [linha for linha in substanciais if linha in instrucao]
    assert vazadas == [], f"{len(vazadas)} linhas do regulamento na instrução"

    # E a instrução é curta: não há como esconder o arquivo dentro dela.
    assert len(instrucao) < len(REGULAMENTO.read_text(encoding="utf-8")) / 10


def test_regulamento_e_tool_e_os_de_dominio_sao_sub_agentes(principal) -> None:
    assert [sub.name for sub in principal.sub_agents] == [
        "especialista_reservas",
        "especialista_visitantes",
    ]

    embrulhados = [t for t in principal.tools if isinstance(t, AgentTool)]
    assert [t.agent.name for t in embrulhados] == ["especialista_regulamento"]

    # O principal não tem tool de domínio própria: ele encaminha, não executa.
    assert [t for t in principal.tools if not isinstance(t, AgentTool)] == []


def test_so_o_especialista_de_regulamento_le_o_regulamento(principal) -> None:
    por_nome = {sub.name: sub for sub in principal.sub_agents}
    tools_de_dominio = {
        t.name for sub in por_nome.values() for t in sub.tools
    }
    assert "ler_capitulo_do_regulamento" not in tools_de_dominio
    assert "listar_capitulos_do_regulamento" not in tools_de_dominio

    regulamento = next(t for t in principal.tools if isinstance(t, AgentTool)).agent
    assert {t.name for t in regulamento.tools} == {
        "listar_capitulos_do_regulamento",
        "ler_capitulo_do_regulamento",
    }
    # E ele não tem tool que grave nada: consultar não muda o condomínio.
    assert regulamento.sub_agents == []
