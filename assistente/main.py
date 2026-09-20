"""Comando de subida: valida o ambiente, prepara o banco e serve em localhost:8000."""

from __future__ import annotations

import sys

import uvicorn

from .configuracao import PORTA, VariavelDeAmbienteAusente, carregar_configuracao


def principal() -> int:
    """Sobe a API, ou recusa antes de abrir a porta quando falta variável.

    A validação vem antes de `uvicorn.run` de propósito: sem chave, o processo
    encerra sem nunca escutar em 8000 e sem nenhuma chamada ao modelo ter saído.
    """
    try:
        configuracao = carregar_configuracao()
    except VariavelDeAmbienteAusente as erro:
        print(f"erro: {erro}", file=sys.stderr)
        return 2

    from .aplicacao import construir_api

    uvicorn.run(construir_api(configuracao), host="127.0.0.1", port=PORTA)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
