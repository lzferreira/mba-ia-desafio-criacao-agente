"""Comando de restauração: volta reservas e visitantes ao estado de `dados/`.

Roda sem argumento e sem chave de API. Os arquivos de `dados/` são só lidos — a
restauração escreve no banco do condomínio, nunca neles.
"""

from __future__ import annotations

import sys

from . import armazenamento
from .configuracao import caminhos_padrao


def principal() -> int:
    caminhos = caminhos_padrao()
    armazenamento.restaurar(
        caminhos.banco_do_condominio,
        caminhos.banco_de_sessoes,
        caminhos.diretorio_de_dados,
    )
    print(f"Dados do condomínio restaurados em {caminhos.banco_do_condominio}.")
    print(f"Sessões apagadas em {caminhos.banco_de_sessoes}.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
