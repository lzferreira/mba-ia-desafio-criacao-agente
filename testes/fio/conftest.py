"""Bancada de fio: API viva, bancos em disco, modelo roteirizado."""

from __future__ import annotations

from pathlib import Path

import pytest

from .modelo_de_bancada import ModeloDeBancada
from .servidor import Bancada, montar, montar_com


@pytest.fixture
async def bancada(tmp_path: Path) -> Bancada:
    montada = montar(tmp_path / "estado")
    try:
        yield montada
    finally:
        await montada.cliente.aclose()


@pytest.fixture
async def bancada_realista(tmp_path: Path) -> Bancada:
    """Bancada com o modelo que decide pelo texto, sem roteiro alimentado.

    O que ela responde vem das tools e dos arquivos, não de uma constante do
    teste — é a montagem certa para asseverar o conteúdo de uma resposta.
    """
    montada = montar_com(tmp_path / "estado", ModeloDeBancada())
    try:
        yield montada
    finally:
        await montada.cliente.aclose()


async def criar_sessao(bancada: Bancada, apartamento: str) -> str:
    resposta = await bancada.cliente.post("/sessoes", json={"apartamento": apartamento})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["session_id"]
