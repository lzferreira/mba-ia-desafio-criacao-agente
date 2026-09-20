"""Bancada de fio: API viva, bancos em disco, modelo roteirizado."""

from __future__ import annotations

from pathlib import Path

import pytest

from .servidor import Bancada, montar


@pytest.fixture
async def bancada(tmp_path: Path) -> Bancada:
    montada = montar(tmp_path / "estado")
    try:
        yield montada
    finally:
        await montada.cliente.aclose()


async def criar_sessao(bancada: Bancada, apartamento: str) -> str:
    resposta = await bancada.cliente.post("/sessoes", json={"apartamento": apartamento})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["session_id"]
