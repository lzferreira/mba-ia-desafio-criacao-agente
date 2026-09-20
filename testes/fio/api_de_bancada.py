"""Sobe a API na porta do contrato com o modelo de bancada no lugar do Gemini.

Entra pelo mesmo `construir_api` da produção: o que muda é a fábrica de modelo da
`Configuracao`, e nada mais. É o que deixa o roteiro do avaliador ser provado
inteiro sem consumir quota.
"""

from __future__ import annotations

import sys

import uvicorn

from assistente.aplicacao import construir_api
from assistente.configuracao import PORTA, Configuracao, caminhos_padrao

from .modelo_de_bancada import ModeloDeBancada


def principal() -> int:
    caminhos = caminhos_padrao()
    configuracao = Configuracao(
        banco_do_condominio=caminhos.banco_do_condominio,
        banco_de_sessoes=caminhos.banco_de_sessoes,
        diretorio_de_dados=caminhos.diretorio_de_dados,
        fabrica_de_modelo=ModeloDeBancada,
    )
    uvicorn.run(construir_api(configuracao), host="127.0.0.1", port=PORTA)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
