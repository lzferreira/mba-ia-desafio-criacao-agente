"""Peças compartilhadas pelas provas: cópias isoladas do projeto e servidor de verdade."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

RAIZ = Path(__file__).resolve().parent.parent
PYTHON_DO_PROJETO = RAIZ / ".venv" / "bin" / "python"
PORTA_DO_CONTRATO = 8000
BASE_DO_CONTRATO = f"http://localhost:{PORTA_DO_CONTRATO}"


def copiar_projeto(destino: Path) -> Path:
    """Copia o que a subida precisa para uma raiz isolada.

    `assistente.configuracao.RAIZ` sai de `Path(__file__).resolve()`, então uma
    cópia de verdade (não um link) é o que faz o processo enxergar `var/` e `.env`
    do diretório do teste em vez dos do repositório.
    """
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copytree(RAIZ / "assistente", destino / "assistente")
    shutil.copytree(RAIZ / "dados", destino / "dados")
    shutil.copytree(RAIZ / "roteiro", destino / "roteiro")
    return destino


def ambiente_sem_chave() -> dict[str, str]:
    ambiente = {
        chave: valor
        for chave, valor in os.environ.items()
        if chave not in {"GOOGLE_API_KEY", "GEMINI_MODEL"}
    }
    ambiente["PYTHONUNBUFFERED"] = "1"
    return ambiente


def porta_livre(porta: int = PORTA_DO_CONTRATO) -> bool:
    with socket.socket() as sonda:
        sonda.settimeout(0.2)
        return sonda.connect_ex(("127.0.0.1", porta)) != 0


def esperar_a_porta(porta: int, processo: subprocess.Popen, limite: float = 25.0) -> None:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if processo.poll() is not None:
            saida = (processo.stdout.read() if processo.stdout else "") or ""
            raise AssertionError(f"a API morreu antes de escutar:\n{saida}")
        with socket.socket() as sonda:
            sonda.settimeout(0.2)
            if sonda.connect_ex(("127.0.0.1", porta)) == 0:
                return
        time.sleep(0.2)
    raise AssertionError(f"a API não escutou em {porta} dentro de {limite}s")


class ApiDeVerdade:
    """Sobe `python -m assistente.main` num processo, como o README manda.

    Existe para as provas que falam de `localhost:8000`, de reinício e de disputa:
    nenhuma delas é verdade sobre o processo se o processo não existir.
    """

    def __init__(self, raiz: Path, ambiente: dict[str, str] | None = None) -> None:
        self.raiz = raiz
        self.ambiente = ambiente or {}
        self.processo: subprocess.Popen | None = None

    def subir(self) -> None:
        ambiente = ambiente_sem_chave()
        ambiente["GOOGLE_API_KEY"] = "chave-de-teste"
        ambiente.update(self.ambiente)
        ambiente["PYTHONPATH"] = str(self.raiz)
        self.processo = subprocess.Popen(
            [str(PYTHON_DO_PROJETO), "-m", "assistente.main"],
            cwd=self.raiz,
            env=ambiente,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        esperar_a_porta(PORTA_DO_CONTRATO, self.processo)

    def parar(self) -> None:
        if self.processo is None:
            return
        self.processo.terminate()
        try:
            self.processo.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.processo.kill()
            self.processo.wait(timeout=10)
        self.processo = None

    def __enter__(self) -> "ApiDeVerdade":
        self.subir()
        return self

    def __exit__(self, *_: object) -> None:
        self.parar()


@pytest.fixture
def raiz_isolada(tmp_path: Path) -> Path:
    return copiar_projeto(tmp_path / "projeto")


@pytest.fixture
def cliente_do_contrato() -> httpx.Client:
    with httpx.Client(base_url=BASE_DO_CONTRATO, timeout=30.0) as cliente:
        yield cliente


@pytest.fixture(autouse=True, scope="session")
def _venv_existe() -> None:
    if not PYTHON_DO_PROJETO.exists():
        pytest.skip(f"rode `uv sync` primeiro: {PYTHON_DO_PROJETO} não existe")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "contrato: usa a porta fixa 8000 do contrato")


if sys.version_info < (3, 12):  # pragma: no cover
    raise RuntimeError("o projeto exige Python 3.12 ou superior")
