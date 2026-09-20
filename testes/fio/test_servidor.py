"""C4, C6 — o processo de subida atende em localhost:8000 com os dados iniciais."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from testes.conftest import (
    BASE_DO_CONTRATO,
    PYTHON_DO_PROJETO,
    ApiDeVerdade,
    ambiente_sem_chave,
    porta_livre,
)

pytestmark = pytest.mark.contrato


def _restaurar(raiz: Path) -> None:
    ambiente = ambiente_sem_chave()
    ambiente["PYTHONPATH"] = str(raiz)
    concluido = subprocess.run(
        [str(PYTHON_DO_PROJETO), "-m", "assistente.restaurar"],
        cwd=raiz,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert concluido.returncode == 0, concluido.stderr


def test_api_responde_em_localhost_8000_com_os_dados_iniciais(
    raiz_isolada: Path,
) -> None:
    if not porta_livre():
        pytest.skip("a porta 8000 do contrato está ocupada por outro processo")
    _restaurar(raiz_isolada)

    with ApiDeVerdade(raiz_isolada):
        with httpx.Client(base_url=BASE_DO_CONTRATO, timeout=30.0) as cliente:
            reservas = cliente.get("/apartamentos/101/reservas")
            visitantes = cliente.get("/apartamentos/302/visitantes")

    assert reservas.status_code == 200
    assert reservas.json() == [
        {"codigo": "RSV-1377", "area": "quadra", "data": "2030-03-09"}
    ]
    assert visitantes.status_code == 200
    assert visitantes.json() == [{"nome": "Marina Duarte", "data": "2030-03-16"}]


def test_subida_sem_banco_semeia_antes_de_atender(raiz_isolada: Path) -> None:
    if not porta_livre():
        pytest.skip("a porta 8000 do contrato está ocupada por outro processo")
    assert not (raiz_isolada / "var" / "condominio.db").exists()

    with ApiDeVerdade(raiz_isolada):
        with httpx.Client(base_url=BASE_DO_CONTRATO, timeout=30.0) as cliente:
            # A primeira requisição que o processo atende já enxerga os dados de
            # `dados/`: a semeadura aconteceu antes de a porta abrir.
            primeira = cliente.get("/apartamentos/201/reservas")

    assert primeira.status_code == 200
    assert primeira.json() == [
        {"codigo": "RSV-2950", "area": "churrasqueira", "data": "2030-03-23"}
    ]
    assert (raiz_isolada / "var" / "condominio.db").exists()
