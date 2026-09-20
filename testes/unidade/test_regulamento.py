"""C45 — o recorte por capítulo, varrido sobre os catorze."""

from __future__ import annotations

from assistente import regulamento
from testes.conftest import RAIZ

CAMINHO = RAIZ / "dados" / "regulamento.md"

ROMANOS = [
    "I", "II", "III", "IV", "V", "VI", "VII",
    "VIII", "IX", "X", "XI", "XII", "XIII", "XIV",
]


def test_o_indice_cobre_os_catorze_capitulos_em_ordem() -> None:
    capitulos = regulamento.listar(CAMINHO)
    assert [c["capitulo"] for c in capitulos] == ROMANOS
    # O índice não carrega texto: só numeração e título.
    for capitulo in capitulos:
        assert set(capitulo) == {"capitulo", "titulo"}
        assert "Art." not in capitulo["titulo"]


def test_cada_capitulo_comeca_no_proprio_titulo_e_para_antes_do_proximo() -> None:
    """Varre os catorze: nenhum recorte invade o capítulo seguinte."""
    capitulos = [regulamento.ler(CAMINHO, romano) for romano in ROMANOS]
    assert all(c is not None for c in capitulos)

    for posicao, capitulo in enumerate(capitulos):
        assert capitulo.texto.startswith(f"## Capítulo {capitulo.numero}:")
        seguintes = ROMANOS[posicao + 1 :]
        for romano in seguintes:
            assert f"## Capítulo {romano}:" not in capitulo.texto

    inteiro = CAMINHO.read_text(encoding="utf-8")
    assert all(len(c.texto) < len(inteiro) for c in capitulos)


def test_capitulo_da_piscina_traz_o_horario_de_domingo() -> None:
    """O Art. 22, II é o que a pergunta do passo 12 do avaliador precisa."""
    piscina = regulamento.ler(CAMINHO, "IV")
    assert piscina is not None
    assert piscina.titulo == "Piscina"
    assert "Aos domingos e feriados, a piscina funciona das 9h às 20h" in piscina.texto
    assert "20h" in piscina.texto

    # E o capítulo da piscina não arrasta assunto alheio junto.
    assert "coleira refletiva cor de mostarda" not in piscina.texto
    assert "dez quilômetros por hora" not in piscina.texto


def test_o_capitulo_pode_ser_pedido_pelo_titulo() -> None:
    por_titulo = regulamento.ler(CAMINHO, "Piscina")
    assert por_titulo is not None and por_titulo.numero == "IV"
    assert regulamento.ler(CAMINHO, "Capítulo IV").numero == "IV"


def test_capitulo_inexistente_devolve_nada() -> None:
    assert regulamento.ler(CAMINHO, "XXIII") is None
    assert regulamento.ler(CAMINHO, "piscina aquecida") is None
