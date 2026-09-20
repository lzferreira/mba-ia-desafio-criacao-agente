"""As seis rotas do contrato do enunciado.

As rotas de verificação leem o banco do condomínio direto, sem passar pelo modelo.
"""

from __future__ import annotations

from fastapi import FastAPI

from . import armazenamento
from .aplicacao import Aplicacao


def criar_api(aplicacao: Aplicacao) -> FastAPI:
    api = FastAPI(title="Assistente do Residencial Aurora")

    @api.get("/apartamentos/{numero}/reservas")
    def reservas_do_apartamento(numero: str) -> list[dict]:
        with aplicacao.banco() as conexao:
            return armazenamento.reservas_do_apartamento(conexao, numero)

    @api.get("/apartamentos/{numero}/visitantes")
    def visitantes_do_apartamento(numero: str) -> list[dict]:
        with aplicacao.banco() as conexao:
            return armazenamento.visitantes_do_apartamento(conexao, numero)

    return api
