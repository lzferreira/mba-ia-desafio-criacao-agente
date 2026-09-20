"""Recorte de `dados/regulamento.md` por capítulo.

Garantia 4 mora aqui e na topologia: o arquivo nunca entra em instrução de agente
e nunca é devolvido inteiro. Uma consulta lê um capítulo, que é a unidade temática
do documento — os catorze tratam cada um de um assunto.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CABECALHO = re.compile(r"^##\s+(Capítulo\s+([IVXL]+))\s*:\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Capitulo:
    numero: str
    titulo: str
    texto: str


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").lower()


@lru_cache(maxsize=4)
def _capitulos(caminho: str) -> tuple[Capitulo, ...]:
    texto = Path(caminho).read_text(encoding="utf-8")
    marcas = list(CABECALHO.finditer(texto))
    capitulos = []
    for posicao, marca in enumerate(marcas):
        inicio = marca.start()
        fim = marcas[posicao + 1].start() if posicao + 1 < len(marcas) else len(texto)
        capitulos.append(
            Capitulo(
                numero=marca.group(2),
                titulo=marca.group(3),
                texto=texto[inicio:fim].strip(),
            )
        )
    return tuple(capitulos)


def listar(caminho: Path) -> list[dict[str, str]]:
    """Devolve só numeração e título — nenhum artigo, nenhum parágrafo."""
    return [
        {"capitulo": c.numero, "titulo": c.titulo} for c in _capitulos(str(caminho))
    ]


def ler(caminho: Path, numero: str) -> Capitulo | None:
    """Devolve um capítulo, nunca o arquivo.

    Aceita a numeração romana (`IV`), com ou sem o prefixo `Capítulo`, e também o
    título, porque é assim que o modelo costuma escrever o que quer ler.
    """
    procurado = _sem_acento(numero).replace("capitulo", "").strip(" :")
    for capitulo in _capitulos(str(caminho)):
        if procurado == capitulo.numero.lower():
            return capitulo
        if procurado == _sem_acento(capitulo.titulo):
            return capitulo
    return None
