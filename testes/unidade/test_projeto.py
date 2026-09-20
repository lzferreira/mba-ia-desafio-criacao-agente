"""C7, C8 — o que o passo 15 do avaliador confere no repositório."""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from testes.conftest import RAIZ

VERSAO_DO_ADK = "2.9.2"


def _pyproject() -> dict:
    return tomllib.loads((RAIZ / "pyproject.toml").read_text("utf-8"))


def test_pyproject_fixa_adk_exato_e_python_312() -> None:
    projeto = _pyproject()["project"]
    assert projeto["requires-python"] == ">=3.12"

    fixadas = [d for d in projeto["dependencies"] if d.startswith("google-adk")]
    assert fixadas == [f"google-adk=={VERSAO_DO_ADK}"]

    # Nenhuma dependência entra com faixa: o avaliador confere versão exata.
    for dependencia in projeto["dependencies"]:
        assert "==" in dependencia, dependencia
        assert not re.search(r"[><~^]", dependencia), dependencia

    assert (RAIZ / "uv.lock").exists()
    versionado = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "uv.lock"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    assert versionado.returncode == 0, "uv.lock precisa estar versionado"


def test_uv_sync_instala_sem_erro_em_clone_limpo(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    clone.mkdir()
    for nome in ("pyproject.toml", "uv.lock", "README.md"):
        origem = RAIZ / nome
        if origem.exists():
            shutil.copy2(origem, clone / nome)
    for pacote in ("assistente", "roteiro", "dados"):
        shutil.copytree(RAIZ / pacote, clone / pacote)

    sincronizado = subprocess.run(
        ["uv", "sync", "--locked"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert sincronizado.returncode == 0, sincronizado.stderr

    instaladas = subprocess.run(
        ["uv", "pip", "list", "--format", "freeze"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert f"google-adk=={VERSAO_DO_ADK}" in instaladas.stdout


def test_env_fora_do_git_e_exemplo_sem_valores() -> None:
    versionados = subprocess.run(
        ["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True
    ).stdout.splitlines()

    assert ".env" not in versionados
    assert ".env.example" in versionados
    assert ".env" in (RAIZ / ".gitignore").read_text("utf-8").splitlines()

    exemplo = (RAIZ / ".env.example").read_text("utf-8")
    nomes = [
        linha.split("=", 1)[0]
        for linha in exemplo.splitlines()
        if linha.strip() and not linha.startswith("#")
    ]
    assert "GOOGLE_API_KEY" in nomes
    for linha in exemplo.splitlines():
        if linha.strip() and not linha.startswith("#"):
            assert linha.split("=", 1)[1] == "", f"{linha} traz valor"

    # Nenhuma chave de API em arquivo versionado: as do Google AI Studio começam
    # com AIza e têm 39 caracteres.
    padrao = re.compile(r"AIza[0-9A-Za-z_-]{35}")
    for caminho in versionados:
        arquivo = RAIZ / caminho
        if not arquivo.is_file():
            continue
        try:
            conteudo = arquivo.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        assert not padrao.search(conteudo), f"chave de API em {caminho}"
