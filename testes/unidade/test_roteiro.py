"""C51 — a primeira verificação que falha para o roteiro e nomeia onde foi."""

from __future__ import annotations

import httpx

from roteiro.avaliador import (
    PASSOS,
    Contexto,
    FalhaDeVerificacao,
    _pendencias_com,
    executar,
)


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


class ClienteFalso:
    """Registra o que o roteiro mandou e devolve respostas roteirizadas."""

    def __init__(self, respostas: list[tuple[int, dict]]) -> None:
        self.respostas = list(respostas)
        self.enviadas: list[str] = []

    def post(self, caminho: str, json: dict) -> httpx.Response:
        self.enviadas.append(json.get("texto", ""))
        codigo, corpo = self.respostas.pop(0)
        return httpx.Response(
            codigo, json=corpo, request=httpx.Request("POST", "http://t" + caminho)
        )


def _contexto_com(respostas: list[tuple[int, dict]]) -> tuple[Contexto, ClienteFalso]:
    cliente = ClienteFalso(respostas)
    contexto = Contexto()
    contexto.cliente = cliente
    return contexto, cliente


SEM_PENDENCIA = {"resposta": "Quer que eu reserve?", "confirmacoes_pendentes": []}
COM_PENDENCIA = {
    "resposta": "",
    "confirmacoes_pendentes": [
        {"id": "c1", "acao": "reservar_area", "detalhes": {"area": "quadra"}}
    ],
}


def test_seguimento_so_sai_quando_nada_ficou_pendente() -> None:
    """A tolerância do roteiro tem um gatilho só, e ele é a ausência de pendência."""
    contexto, cliente = _contexto_com([(200, SEM_PENDENCIA), (200, COM_PENDENCIA)])

    resposta = contexto.enviar_ate_pendencia("s1", "Reserve a quadra.", "Sim, pode.")

    assert cliente.enviadas == ["Reserve a quadra.", "Sim, pode."]
    assert resposta.json()["confirmacoes_pendentes"][0]["id"] == "c1"


def test_sem_seguimento_quando_a_pendencia_ja_veio() -> None:
    """Uma mensagem só. O seguimento não é um retry cego."""
    contexto, cliente = _contexto_com([(200, COM_PENDENCIA)])

    contexto.enviar_ate_pendencia("s1", "Reserve o salão.", "Sim, pode.")

    assert cliente.enviadas == ["Reserve o salão."]


def test_sem_seguimento_quando_a_rota_nao_respondeu_200() -> None:
    """Um 503 ou 404 é para o passo ver, não para o roteiro insistir por cima."""
    contexto, cliente = _contexto_com([(503, {"detail": "indisponível"})])

    resposta = contexto.enviar_ate_pendencia("s1", "Reserve o salão.", "Sim, pode.")

    assert cliente.enviadas == ["Reserve o salão."]
    assert resposta.status_code == 503


def test_pendencias_com_filtra_pelos_detalhes_esperados() -> None:
    """Duas pendências iguais contam; uma de outra área ou data não conta."""
    resposta = httpx.Response(
        200,
        json={
            "resposta": "",
            "confirmacoes_pendentes": [
                {"id": "a", "acao": "reservar_area",
                 "detalhes": {"area": "salao-de-festas", "data": "2030-04-20"}},
                {"id": "b", "acao": "reservar_area",
                 "detalhes": {"data": "2030-04-20", "area": "salao-de-festas"}},
                {"id": "c", "acao": "reservar_area",
                 "detalhes": {"area": "churrasqueira", "data": "2030-04-20"}},
            ],
        },
        request=httpx.Request("POST", "http://t/x"),
    )

    batem = _pendencias_com(resposta, area="salao-de-festas", data="2030-04-20")
    assert [p["id"] for p in batem] == ["a", "b"]

    assert _pendencias_com(resposta, area="quadra", data="2030-04-20") == []
    assert _pendencias_com(resposta, area="salao-de-festas", data="2030-05-11") == []
