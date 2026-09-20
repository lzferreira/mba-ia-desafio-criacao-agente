"""C14, C29 — o apartamento fora das assinaturas e a confirmação onde ela é devida.

As duas provas varrem o conjunto inteiro de tools registradas, não uma amostra: é
o que faz a garantia valer para a próxima tool que alguém acrescentar, e não só
para as que existiam no dia em que o teste foi escrito.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from assistente import armazenamento
from assistente.aplicacao import Aplicacao
from assistente.configuracao import Configuracao
from assistente.ferramentas import (
    TOOLS_QUE_EXIGEM_CONFIRMACAO,
    SessaoSemApartamento,
    apartamento_da_sessao,
    construir_ferramentas,
)
from testes.conftest import RAIZ


@pytest.fixture
def aplicacao(tmp_path: Path) -> Aplicacao:
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


def todas_as_tools(aplicacao: Aplicacao) -> list[FunctionTool]:
    return [t for grupo in construir_ferramentas(aplicacao).values() for t in grupo]


class EstadoFalso:
    def __init__(self, conteudo: dict) -> None:
        self._conteudo = conteudo

    def get(self, chave, padrao=None):
        return self._conteudo.get(chave, padrao)


class ContextoFalso:
    """Só o que as tools usam do ToolContext: o state e a confirmação."""

    def __init__(self, estado: dict, confirmacao=None) -> None:
        self.state = EstadoFalso(estado)
        self.tool_confirmation = confirmacao


def test_nenhuma_tool_declara_parametro_de_apartamento(aplicacao: Aplicacao) -> None:
    ferramentas = todas_as_tools(aplicacao)
    assert len(ferramentas) == 9

    for ferramenta in ferramentas:
        assinatura = inspect.signature(ferramenta.func)
        suspeitos = [
            nome
            for nome in assinatura.parameters
            if "apartamento" in nome.lower() or "apto" in nome.lower()
        ]
        assert suspeitos == [], f"{ferramenta.name} aceita {suspeitos}"


def test_tools_usam_o_apartamento_do_state_da_sessao(aplicacao: Aplicacao) -> None:
    grupos = construir_ferramentas(aplicacao)
    por_nome = {t.name: t for grupo in grupos.values() for t in grupo}

    listar = por_nome["listar_minhas_reservas"].func
    assert listar(ContextoFalso({"apartamento": "101"}))["reservas"] == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]
    assert listar(ContextoFalso({"apartamento": "302"}))["reservas"] == [
        {"codigo": "RSV-4821", "area": "salao-de-festas", "data": "2030-03-16"}
    ]

    # Sem apartamento no state nenhuma tool de domínio anda: não existe default.
    with pytest.raises(SessaoSemApartamento):
        listar(ContextoFalso({}))
    with pytest.raises(SessaoSemApartamento):
        apartamento_da_sessao(ContextoFalso({"apartamento": ""}))


def test_toda_tool_de_cobranca_ou_acesso_exige_confirmacao(aplicacao: Aplicacao) -> None:
    """Varre as 9 tools: as que gravam cobrança ou liberam acesso pedem confirmação.

    A checagem roda `check_require_confirmation` de verdade, com os argumentos que
    o modelo mandaria, porque é essa chamada que o ADK usa para decidir se para.
    """
    ferramentas = todas_as_tools(aplicacao)
    argumentos_por_tool = {
        "consultar_areas": {},
        "consultar_disponibilidade": {"area": "salao-de-festas", "data": "2030-04-20"},
        "listar_minhas_reservas": {},
        "reservar_area": {"area": "salao-de-festas", "data": "2030-04-20"},
        "cancelar_reserva": {"area": "quadra", "data": "2030-03-09"},
        "listar_meus_visitantes": {},
        "autorizar_visitante": {"nome": "Joana Ribeiro", "data": "2030-04-21"},
        "listar_capitulos_do_regulamento": {},
        "ler_capitulo_do_regulamento": {"capitulo": "IV"},
    }
    assert set(argumentos_por_tool) == {f.name for f in ferramentas}

    contexto = ContextoFalso({"apartamento": "101"})
    for ferramenta in ferramentas:
        exige = asyncio.run(
            ferramenta.check_require_confirmation(
                argumentos_por_tool[ferramenta.name], contexto
            )
        )
        assert exige is (ferramenta.name in TOOLS_QUE_EXIGEM_CONFIRMACAO), (
            f"{ferramenta.name} decidiu confirmação errado"
        )

    # A quadra tem taxa 0: a mesma tool não pede confirmação para ela.
    reservar = next(f for f in ferramentas if f.name == "reservar_area")
    assert (
        asyncio.run(
            reservar.check_require_confirmation(
                {"area": "quadra", "data": "2030-04-06"}, contexto
            )
        )
        is False
    )
    # E a churrasqueira, taxa 80, pede.
    assert (
        asyncio.run(
            reservar.check_require_confirmation(
                {"area": "churrasqueira", "data": "2030-04-06"}, contexto
            )
        )
        is True
    )


def test_corpo_recusa_gravar_cobranca_ou_acesso_sem_confirmacao(
    aplicacao: Aplicacao,
) -> None:
    """A segunda tranca: mesmo chamado direto, o corpo não grava sem confirmação."""
    por_nome = {
        t.name: t for grupo in construir_ferramentas(aplicacao).values() for t in grupo
    }
    contexto = ContextoFalso({"apartamento": "101"})

    reserva = por_nome["reservar_area"].func("salao-de-festas", "2030-04-20", contexto)
    visita = por_nome["autorizar_visitante"].func(
        "Joana Ribeiro", "2030-04-21", contexto
    )

    assert reserva["ok"] is False and reserva["motivo"] == "sem_confirmacao"
    assert visita["ok"] is False and visita["motivo"] == "sem_confirmacao"

    conexao = armazenamento.conectar(aplicacao.configuracao.banco_do_condominio)
    try:
        assert armazenamento.reservas_do_apartamento(conexao, "101") == [
            {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
        ]
        assert armazenamento.visitantes_do_apartamento(conexao, "101") == []
    finally:
        conexao.close()
