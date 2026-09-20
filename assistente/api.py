"""As seis rotas do contrato do enunciado.

As rotas de verificação leem o banco do condomínio direto, sem passar pelo modelo.
A rota de confirmações recusa antes de executar qualquer coisa: só um id que esteja
pendente nesta sessão passa.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from google.genai import types
from pydantic import BaseModel

from . import armazenamento, pendencias
from .aplicacao import Aplicacao


class NovaSessao(BaseModel):
    apartamento: str


class NovaMensagem(BaseModel):
    texto: str


class RespostaDeConfirmacao(BaseModel):
    id: str
    confirmado: bool


def criar_api(aplicacao: Aplicacao) -> FastAPI:
    api = FastAPI(title="Assistente do Residencial Aurora")

    async def _sessao_ou_404(session_id: str):
        sessao = await aplicacao.obter_sessao(session_id)
        if sessao is None:
            raise HTTPException(status_code=404, detail="sessão não encontrada")
        return sessao

    def _corpo(resposta: str, eventos) -> dict:
        return {
            "resposta": resposta,
            "confirmacoes_pendentes": [
                p.como_json() for p in pendencias.derivar(eventos)
            ],
        }

    @api.post("/sessoes", status_code=201)
    async def criar_sessao(corpo: NovaSessao) -> dict:
        with aplicacao.banco() as conexao:
            if not armazenamento.apartamento_existe(conexao, corpo.apartamento):
                raise HTTPException(
                    status_code=404, detail="apartamento não encontrado"
                )
        return {"session_id": await aplicacao.criar_sessao(corpo.apartamento)}

    @api.post("/sessoes/{session_id}/mensagens")
    async def enviar_mensagem(session_id: str, corpo: NovaMensagem) -> dict:
        await _sessao_ou_404(session_id)
        mensagem = types.Content(
            role="user", parts=[types.Part.from_text(text=corpo.texto)]
        )
        resposta, _ = await aplicacao.conversar(session_id, mensagem)
        return _corpo(resposta, await aplicacao.eventos(session_id))

    @api.post("/sessoes/{session_id}/confirmacoes")
    async def responder_confirmacao(
        session_id: str, corpo: RespostaDeConfirmacao
    ) -> dict:
        sessao = await _sessao_ou_404(session_id)

        pendencia = pendencias.encontrar(sessao.events, corpo.id)
        if pendencia is None:
            # Id que nunca existiu, id de outra sessão, ou id já respondido — os
            # três deixam de estar pendentes aqui, e nenhum chega ao Runner.
            raise HTTPException(
                status_code=409,
                detail="não existe confirmação pendente com esse id nesta sessão",
            )

        resposta, novos = await aplicacao.conversar(
            session_id, pendencias.resposta_de_confirmacao(corpo.id, corpo.confirmado)
        )
        if corpo.confirmado:
            pendencias.conferir_retomada(pendencia, novos, session_id)
        return _corpo(resposta, await aplicacao.eventos(session_id))

    @api.get("/sessoes/{session_id}/eventos")
    async def eventos_da_sessao(session_id: str) -> list[dict]:
        sessao = await _sessao_ou_404(session_id)
        return [
            json.loads(evento.model_dump_json(exclude_none=True, by_alias=True))
            for evento in sessao.events
        ]

    @api.get("/apartamentos/{numero}/reservas")
    def reservas_do_apartamento(numero: str) -> list[dict]:
        with aplicacao.banco() as conexao:
            return armazenamento.reservas_do_apartamento(conexao, numero)

    @api.get("/apartamentos/{numero}/visitantes")
    def visitantes_do_apartamento(numero: str) -> list[dict]:
        with aplicacao.banco() as conexao:
            return armazenamento.visitantes_do_apartamento(conexao, numero)

    return api
