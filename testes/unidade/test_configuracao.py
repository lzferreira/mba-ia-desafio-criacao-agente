"""C1 — a subida recusa antes de escutar quando falta a chave do modelo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from assistente.configuracao import (
    MODELO_PADRAO,
    VARIAVEL_DA_CHAVE,
    VariavelDeAmbienteAusente,
    carregar_configuracao,
)
from testes.conftest import PYTHON_DO_PROJETO, ambiente_sem_chave


def test_subida_sem_chave_encerra_nomeando_a_variavel(raiz_isolada: Path) -> None:
    ambiente = ambiente_sem_chave()
    ambiente["PYTHONPATH"] = str(raiz_isolada)

    concluido = subprocess.run(
        [str(PYTHON_DO_PROJETO), "-m", "assistente.main"],
        cwd=raiz_isolada,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert concluido.returncode != 0
    assert VARIAVEL_DA_CHAVE in concluido.stderr
    # O uvicorn nunca chegou a abrir a porta: sem esta linha no stdout, o processo
    # encerrou antes de escutar em localhost:8000 e antes de construir agente algum.
    assert "Uvicorn running on" not in concluido.stdout
    assert not (raiz_isolada / "var" / "condominio.db").exists()


def test_chave_em_branco_conta_como_ausente() -> None:
    with pytest.raises(VariavelDeAmbienteAusente) as erro:
        carregar_configuracao({VARIAVEL_DA_CHAVE: "   "})
    assert erro.value.nome == VARIAVEL_DA_CHAVE


def test_modelo_cai_no_padrao_quando_a_variavel_nao_vem() -> None:
    configuracao = carregar_configuracao({VARIAVEL_DA_CHAVE: "chave"})
    assert configuracao.fabrica_de_modelo() == MODELO_PADRAO


def test_modelo_do_ambiente_vence_o_padrao() -> None:
    configuracao = carregar_configuracao(
        {VARIAVEL_DA_CHAVE: "chave", "GEMINI_MODEL": "gemini-outro"}
    )
    assert configuracao.fabrica_de_modelo() == "gemini-outro"
