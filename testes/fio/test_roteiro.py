"""C50, C52, C53 — o roteiro do avaliador roda inteiro, num clone limpo de verdade.

A API que o roteiro sobe aqui é a de produção, pelo mesmo `construir_api`; o que
muda é a fábrica de modelo (`testes/fio/api_de_bancada.py`), porque provar que o
roteiro reinicia a API e dispara duas aprovações concorrentes não pode depender de
quota de modelo. O roteiro contra o Gemini de verdade é `uv run python -m
roteiro.avaliador`, documentado no README.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from roteiro.avaliador import Contexto, executar
from testes.conftest import RAIZ, PYTHON_DO_PROJETO, porta_livre

pytestmark = pytest.mark.contrato

ARQUIVOS = ("pyproject.toml", "uv.lock", ".gitignore", ".env.example", "README.md")
PASTAS = ("assistente", "roteiro", "dados", "testes")


def clone_limpo(destino: Path) -> Path:
    """Um clone de verdade: com Git, para os passos 13 e 15 terem o que conferir."""
    destino.mkdir(parents=True, exist_ok=True)
    for nome in ARQUIVOS:
        shutil.copy2(RAIZ / nome, destino / nome)
    for pasta in PASTAS:
        shutil.copytree(
            RAIZ / pasta,
            destino / pasta,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    for comando in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=roteiro", "-c", "user.email=roteiro@teste",
         "-c", "commit.gpgsign=false", "commit", "-q", "-m", "clone"],
    ):
        concluido = subprocess.run(
            comando, cwd=destino, capture_output=True, text=True
        )
        assert concluido.returncode == 0, concluido.stderr
    return destino


def contexto_de_bancada(raiz: Path) -> Contexto:
    return Contexto(
        raiz=raiz,
        comando_da_api=[str(PYTHON_DO_PROJETO), "-m", "testes.fio.api_de_bancada"],
        comando_de_restauracao=[str(PYTHON_DO_PROJETO), "-m", "assistente.restaurar"],
    )


@pytest.fixture(scope="module")
def roteiro_executado(tmp_path_factory) -> Contexto:
    """Roda o roteiro uma vez e deixa o contexto para as três provas lerem.

    Uma execução só, porque ela sobe e derruba servidores de verdade na porta do
    contrato — e porque os três checks falam do mesmo percurso.
    """
    if not porta_livre():
        pytest.skip("a porta 8000 do contrato está ocupada por outro processo")

    raiz = clone_limpo(tmp_path_factory.mktemp("clone") / "projeto")
    contexto = contexto_de_bancada(raiz)
    contexto.codigo_de_saida = executar(contexto)
    return contexto


def test_roteiro_executa_os_quinze_passos_em_ordem(roteiro_executado: Contexto) -> None:
    saida = "\n".join(roteiro_executado.saida)
    assert roteiro_executado.codigo_de_saida == 0, saida

    # Cada passo imprimiu o resultado das suas verificações, e nenhum ficou de fora.
    for numero in range(1, 16):
        assert f"passo {numero:>2} ·" in saida, f"o passo {numero} não imprimiu nada"
    assert "FALHOU" not in saida
    assert "Os 15 passos do fluxo do avaliador passaram." in saida


def test_passo_13_reinicia_a_api_e_compara_a_contagem_de_eventos(
    roteiro_executado: Contexto,
) -> None:
    saida = "\n".join(roteiro_executado.saida)
    assert roteiro_executado.eventos_no_passo_12 > 0
    assert (
        f"S1 tem {roteiro_executado.eventos_no_passo_12} eventos" in saida
    )
    assert (
        "passo 13 · depois do reinício, S1 devolve a mesma quantidade de eventos · ok"
        in saida
    )
    assert "passo 13 · a nova mensagem responde 200 · ok" in saida
    assert "passo 13 · a quantidade de eventos aumentou · ok" in saida


def test_passo_14_dispara_duas_aprovacoes_concorrentes(
    roteiro_executado: Contexto,
) -> None:
    saida = "\n".join(roteiro_executado.saida)
    assert "passo 14 · S3 fica com confirmação pendente · ok" in saida
    assert "passo 14 · S4 fica com confirmação pendente · ok" in saida
    assert "passo 14 · as duas aprovações respondem 200 · ok" in saida
    assert (
        "passo 14 · os dois apartamentos somam exatamente uma reserva do salão"
        " em 2030-05-11 · ok" in saida
    )
    assert {"S3", "S4"} <= set(roteiro_executado.sessoes)
    assert roteiro_executado.sessoes["S3"] != roteiro_executado.sessoes["S4"]


def test_o_roteiro_deixa_dados_intactos_no_clone(roteiro_executado: Contexto) -> None:
    sujo = subprocess.run(
        ["git", "status", "--porcelain", "dados/"],
        cwd=roteiro_executado.raiz,
        capture_output=True,
        text=True,
    )
    assert sujo.returncode == 0
    assert sujo.stdout == ""
