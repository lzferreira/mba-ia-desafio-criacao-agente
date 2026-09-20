"""A API montada em processo, com o modelo roteirizado no lugar do Gemini.

Usa `assistente.aplicacao.construir_api`, a mesma função da subida de produção: a
fábrica de modelo da `Configuracao` é o único parâmetro que difere entre as duas
montagens, então não existe uma segunda montagem para sair de sincronia com esta.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
from google.adk.models.llm_response import LlmResponse
from google.adk.sessions.sqlite_session_service import SqliteSessionService

from assistente import armazenamento
from assistente.aplicacao import USUARIO, construir_api
from assistente.configuracao import NOME_DO_APP, Configuracao

from .modelo import ModeloRoteirizado, roteirizar

RAIZ_DO_PROJETO = Path(__file__).resolve().parent.parent.parent
DIRETORIO_DE_DADOS = RAIZ_DO_PROJETO / "dados"


@dataclass
class Bancada:
    """Uma API viva sobre bancos de verdade em disco, com um roteiro no modelo."""

    diretorio: Path
    modelo: ModeloRoteirizado
    cliente: httpx.AsyncClient

    @property
    def banco_do_condominio(self) -> Path:
        return self.diretorio / "condominio.db"

    @property
    def banco_de_sessoes(self) -> Path:
        return self.diretorio / "sessoes.db"

    def roteirizar(self, **por_agente: list[LlmResponse]) -> None:
        """Substitui o roteiro sem trocar o modelo que os agentes já seguram."""
        self.modelo.roteiro = {
            agente: list(turnos) for agente, turnos in por_agente.items()
        }
        self.modelo.chamadas = []

    def conexao(self):
        return armazenamento.conectar(self.banco_do_condominio)

    async def estado_persistido(self, session_id: str) -> dict:
        """Lê o state direto do arquivo de sessões, por um serviço recém-aberto.

        Nada da montagem em pé é reaproveitado: o que voltar daqui está no disco.
        """
        servico = SqliteSessionService(str(self.banco_de_sessoes))
        sessao = await servico.get_session(
            app_name=NOME_DO_APP, user_id=USUARIO, session_id=session_id
        )
        return dict(sessao.state) if sessao else {}

    async def reiniciar(self) -> None:
        """Descarta tudo que estava em memória e remonta a API sobre os arquivos.

        Nenhum objeto da montagem anterior sobrevive — nem o serviço de sessão, nem
        o Runner, nem as pendências. O que continuar valendo depois disto só pode
        ter vindo do disco.
        """
        await self.cliente.aclose()
        self.cliente = _cliente(_configuracao(self.diretorio, self.modelo))


def _configuracao(diretorio: Path, modelo: ModeloRoteirizado) -> Configuracao:
    return Configuracao(
        banco_do_condominio=diretorio / "condominio.db",
        banco_de_sessoes=diretorio / "sessoes.db",
        diretorio_de_dados=DIRETORIO_DE_DADOS,
        fabrica_de_modelo=lambda: modelo,
    )


def _cliente(configuracao: Configuracao) -> httpx.AsyncClient:
    api = construir_api(configuracao)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api),
        base_url="http://aurora.teste",
        timeout=60.0,
    )


def montar(diretorio: Path, **roteiro: list[LlmResponse]) -> Bancada:
    return montar_com(diretorio, roteirizar(**roteiro))


def montar_com(diretorio: Path, modelo) -> Bancada:
    """Monta a bancada com o modelo que a prova pedir.

    `ModeloDeBancada` entra por aqui quando a prova não pode alimentar a resposta
    que ela mesma vai asseverar — é o que separa uma prova de verdade de uma que
    só confere a própria constante.
    """
    diretorio.mkdir(parents=True, exist_ok=True)
    armazenamento.restaurar(
        diretorio / "condominio.db", diretorio / "sessoes.db", DIRETORIO_DE_DADOS
    )
    return Bancada(
        diretorio=diretorio,
        modelo=modelo,
        cliente=_cliente(_configuracao(diretorio, modelo)),
    )
