"""Montagem única da aplicação: banco pronto, agentes de pé, rotas no ar.

Produção (`assistente/main.py`) e testes (`testes/fio/servidor.py`) chamam esta
mesma função. O único parâmetro que difere entre as duas montagens é a fábrica de
modelo da `Configuracao` — tudo que precisa valer antes da primeira requisição
vale nas duas por construção, em vez de precisar ser repetido em cada uma.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from fastapi import FastAPI
from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import Runner
from google.adk.sessions import Session
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from . import armazenamento
from .configuracao import NOME_DO_APP, Configuracao

USUARIO = "morador"
CHAVE_DO_APARTAMENTO = "apartamento"


@dataclass
class Aplicacao:
    """Estado vivo da API: configuração, banco do condomínio e o Runner do ADK."""

    configuracao: Configuracao
    servico_de_sessoes: SqliteSessionService | None = None
    runner: Runner | None = None
    _sessoes_em_criacao: dict = field(default_factory=dict)

    @contextmanager
    def banco(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão por operação.

        As tools rodam no pool de threads do ADK e as rotas no laço de eventos;
        uma conexão por operação evita compartilhar handle de SQLite entre threads.
        """
        conexao = armazenamento.conectar(self.configuracao.banco_do_condominio)
        try:
            yield conexao
        finally:
            conexao.close()

    # -- sessões ---------------------------------------------------------------

    async def criar_sessao(self, apartamento: str) -> str:
        """Fixa o apartamento no state, uma única vez, na criação da sessão.

        Depois daqui nada reescreve essa chave: é ela que as tools leem, e é o que
        faz a Garantia 2 não depender de nada que o morador escreva.
        """
        sessao = await self.servico_de_sessoes.create_session(
            app_name=NOME_DO_APP,
            user_id=USUARIO,
            state={CHAVE_DO_APARTAMENTO: apartamento},
        )
        return sessao.id

    async def obter_sessao(self, session_id: str) -> Session | None:
        return await self.servico_de_sessoes.get_session(
            app_name=NOME_DO_APP, user_id=USUARIO, session_id=session_id
        )

    async def eventos(self, session_id: str) -> list:
        sessao = await self.obter_sessao(session_id)
        return list(sessao.events) if sessao else []

    async def conversar(
        self, session_id: str, mensagem: types.Content
    ) -> tuple[str, list]:
        """Roda uma invocação e devolve o texto para o morador e os eventos novos."""
        novos: list = []
        partes: list[str] = []
        async for evento in self.runner.run_async(
            user_id=USUARIO, session_id=session_id, new_message=mensagem
        ):
            novos.append(evento)
            if evento.partial:
                continue
            if evento.author == "user" or not evento.content:
                continue
            for parte in evento.content.parts or []:
                if parte.text and not getattr(parte, "thought", False):
                    partes.append(parte.text.strip())
        return "\n".join(p for p in partes if p).strip(), novos


def construir_api(configuracao: Configuracao) -> FastAPI:
    """Prepara o banco, monta os agentes e devolve a API pronta para atender.

    A semeadura acontece aqui, antes de o servidor aceitar a primeira requisição,
    para que uma subida sem banco não atenda com tabelas vazias.
    """
    armazenamento.preparar(
        configuracao.banco_do_condominio, configuracao.diretorio_de_dados
    )

    from . import agentes, api

    aplicacao = Aplicacao(configuracao=configuracao)
    aplicacao.servico_de_sessoes = SqliteSessionService(
        str(configuracao.banco_de_sessoes)
    )
    aplicacao.runner = Runner(
        app=App(
            name=NOME_DO_APP,
            root_agent=agentes.construir_agentes(aplicacao),
            # Sem retomada ligada, `find_agent_to_run` ignora o autor da
            # `functionCall` e devolve a resposta de confirmação ao agente raiz
            # (`agents/_agent_router.py:118-131`). A rota responde 200, o
            # processador de confirmação não encontra a chamada original no agente
            # em que caiu, e a ação nunca executa — em silêncio.
            resumability_config=ResumabilityConfig(is_resumable=True),
        ),
        session_service=aplicacao.servico_de_sessoes,
    )
    return api.criar_api(aplicacao)
