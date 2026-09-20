"""C51 — a primeira verificação que falha para o roteiro e nomeia onde foi."""

from __future__ import annotations

from roteiro.avaliador import PASSOS, Contexto, FalhaDeVerificacao, executar


def test_o_roteiro_tem_os_quinze_passos_na_ordem() -> None:
    assert [passo.__name__ for passo in PASSOS] == [
        f"passo_{numero:02d}" for numero in range(1, 16)
    ]


def test_falha_de_verificacao_para_nomeia_e_sai_diferente_de_zero() -> None:
    andados: list[str] = []

    def primeiro(ctx: Contexto) -> None:
        andados.append("primeiro")
        ctx.conferir("o primeiro passo passa", True)

    def segundo(ctx: Contexto) -> None:
        andados.append("segundo")
        ctx.conferir("o 101 lista a RSV-1377", False, "veio lista vazia")

    def terceiro(ctx: Contexto) -> None:  # pragma: no cover - não deve rodar
        andados.append("terceiro")

    contexto = Contexto()
    codigo = executar(contexto, [primeiro, segundo, terceiro])

    assert codigo != 0
    # Parou no ponto: o terceiro passo nem começou.
    assert andados == ["primeiro", "segundo"]

    saida = "\n".join(contexto.saida)
    assert "passo  2" in saida
    assert "o 101 lista a RSV-1377" in saida
    assert "FALHOU" in saida
    assert "veio lista vazia" in saida
    # E o passo que passou foi impresso como tal, não silenciosamente.
    assert "o primeiro passo passa · ok" in saida


def test_a_verificacao_que_passa_nao_levanta_nada() -> None:
    contexto = Contexto()
    contexto.passo_atual = 7
    contexto.conferir("uma condição verdadeira", True)
    assert contexto.saida == ["passo  7 · uma condição verdadeira · ok"]

    contexto.passo_atual = 8
    try:
        contexto.conferir("uma condição falsa", False)
    except FalhaDeVerificacao as falha:
        assert falha.passo == 8
        assert falha.verificacao == "uma condição falsa"
    else:  # pragma: no cover - a exceção é o comportamento
        raise AssertionError("conferir deveria ter levantado FalhaDeVerificacao")
