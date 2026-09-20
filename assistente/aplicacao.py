"""Montagem única da aplicação: banco pronto, agentes de pé, rotas no ar.

Produção (`assistente/main.py`) e testes (`testes/fio/servidor.py`) chamam esta
mesma função. O único parâmetro que difere entre as duas montagens é a fábrica de
modelo da `Configuracao` — tudo que precisa valer antes da primeira requisição
vale nas duas por construção, em vez de precisar ser repetido em cada uma.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from fastapi import FastAPI

from . import armazenamento
from .configuracao import Configuracao


@dataclass
class Aplicacao:
    """Estado vivo da API: a configuração e o acesso ao banco do condomínio."""

    configuracao: Configuracao

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


def construir_api(configuracao: Configuracao) -> FastAPI:
    """Prepara o banco e devolve a API pronta para atender.

    A semeadura acontece aqui, antes de o servidor aceitar a primeira requisição,
    para que uma subida sem banco não atenda com tabelas vazias.
    """
    armazenamento.preparar(
        configuracao.banco_do_condominio, configuracao.diretorio_de_dados
    )

    from . import api

    aplicacao = Aplicacao(configuracao=configuracao)
    return api.criar_api(aplicacao)
