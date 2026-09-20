"""Configuração lida do ambiente, validada antes de qualquer chamada ao modelo."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DIRETORIO_DE_DADOS = RAIZ / "dados"
DIRETORIO_DE_ESTADO = RAIZ / "var"

VARIAVEL_DA_CHAVE = "GOOGLE_API_KEY"
VARIAVEL_DO_MODELO = "GEMINI_MODEL"
MODELO_PADRAO = "gemini-2.5-flash"

NOME_DO_APP = "aurora"
PORTA = 8000


class VariavelDeAmbienteAusente(RuntimeError):
    """A subida não pode continuar porque falta uma variável obrigatória."""

    def __init__(self, nome: str) -> None:
        self.nome = nome
        super().__init__(
            f"Variável de ambiente {nome} ausente. "
            f"Copie .env.example para .env e preencha {nome} com a sua chave do "
            "Google AI Studio antes de subir a API."
        )


@dataclass(frozen=True)
class Configuracao:
    """Tudo que a aplicação precisa saber antes de atender a primeira requisição.

    `fabrica_de_modelo` é o único ponto em que a montagem de produção e a montagem
    dos testes divergem: em produção devolve o nome do modelo Gemini, nos testes
    devolve um modelo roteirizado. O resto da montagem é a mesma função.
    """

    banco_do_condominio: Path
    banco_de_sessoes: Path
    diretorio_de_dados: Path = DIRETORIO_DE_DADOS
    fabrica_de_modelo: Callable[[], Any] = lambda: MODELO_PADRAO

    caminho_do_regulamento: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "caminho_do_regulamento", self.diretorio_de_dados / "regulamento.md"
        )


@dataclass(frozen=True)
class Caminhos:
    """Onde o estado mutável mora. A restauração precisa disto e de mais nada.

    Restaurar não fala com o modelo, então não exige a chave: o avaliador pode
    restaurar antes de preencher o `.env` sem receber um erro que não é dele.
    """

    banco_do_condominio: Path
    banco_de_sessoes: Path
    diretorio_de_dados: Path


def caminhos_padrao(raiz: Path = RAIZ) -> Caminhos:
    estado = raiz / "var"
    estado.mkdir(parents=True, exist_ok=True)
    return Caminhos(
        banco_do_condominio=estado / "condominio.db",
        banco_de_sessoes=estado / "sessoes.db",
        diretorio_de_dados=raiz / "dados",
    )


def carregar_configuracao(ambiente: dict[str, str] | None = None) -> Configuracao:
    """Lê o `.env` e o ambiente, recusando a subida quando falta a chave do modelo.

    A recusa acontece aqui, antes de o servidor abrir a porta e antes de o primeiro
    agente ser construído, para que a falta de chave nunca vire erro de runtime no
    meio de uma conversa.
    """
    if ambiente is None:
        load_dotenv(RAIZ / ".env")
        ambiente = dict(os.environ)

    chave = (ambiente.get(VARIAVEL_DA_CHAVE) or "").strip()
    if not chave:
        raise VariavelDeAmbienteAusente(VARIAVEL_DA_CHAVE)

    os.environ[VARIAVEL_DA_CHAVE] = chave
    modelo = (ambiente.get(VARIAVEL_DO_MODELO) or "").strip() or MODELO_PADRAO

    caminhos = caminhos_padrao()
    return Configuracao(
        banco_do_condominio=caminhos.banco_do_condominio,
        banco_de_sessoes=caminhos.banco_de_sessoes,
        diretorio_de_dados=caminhos.diretorio_de_dados,
        fabrica_de_modelo=lambda: modelo,
    )
