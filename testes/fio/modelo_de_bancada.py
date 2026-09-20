"""Um Gemini de mentira que se comporta bem, para rodar o roteiro inteiro sem chave.

O roteiro do avaliador é um script de quinze passos contra a API de pé. Provar que
ele faz o que promete — parar no primeiro erro, reiniciar a API no passo 13,
disparar as duas aprovações no passo 14 — não pode depender de quota de modelo nem
da redação que o Gemini escolher no dia.

Este modelo decide pelo texto da mensagem, como um modelo competente decidiria, e
sempre do mesmo jeito. Ele não é o assistente: não grava nada, não sabe de
apartamento e não pode furar regra nenhuma — tudo que ele faz é escolher a próxima
tool. As garantias continuam sendo do código, que é o ponto.
"""

from __future__ import annotations

import re
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from .modelo import NOME_INTERNO, chamar, texto, transferir

DATA = re.compile(r"\d{4}-\d{2}-\d{2}")
NOME_PROPRIO = re.compile(r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ]\w+\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]\w+)\b")

AREAS = (
    ("salao-de-festas", ("salão de festas", "salao de festas", "salão", "salao")),
    ("churrasqueira", ("churrasqueira",)),
    ("quadra", ("quadra",)),
    ("piscina", ("piscina",)),
)

CAPITULOS = (
    ("IV", ("piscina",)),
    ("V", ("academia", "brinquedoteca", "playground")),
    ("VI", ("salão de festas", "churrasqueira", "quadra")),
    ("III", ("silêncio", "barulho", "som")),
    ("VII", ("portaria", "visitante", "segurança")),
    ("VIII", ("animal", "cachorro", "cão", "gato")),
    ("IX", ("mudança",)),
    ("X", ("obra", "reforma")),
    ("XI", ("garagem", "veículo", "carro", "vaga")),
    ("XII", ("lixo", "reciclagem")),
)


# Quando o ADK transfere, o agente que recebe vê o histórico do outro embrulhado
# num turno de usuário que começa por este preâmbulo (`flows/llm_flows/_fencing.py`).
# Esse turno não é o pedido do morador, e confundi-lo com o pedido faz o
# especialista devolver tudo ao principal, que devolve de novo, sem fim.
PREAMBULO_DE_OUTRO_AGENTE = "For context: below is a transcript of what another agent"


def _turno_atual(llm_request: LlmRequest) -> tuple[str, list]:
    """Separa o pedido do morador e o que veio depois dele, nesta rodada.

    O histórico inteiro fica no request, e a resposta de uma tool de uma mensagem
    anterior continua lá. Olhar só o que veio depois do último texto do morador é
    o que impede o modelo de achar que já resolveu o pedido de agora.
    """
    conteudos = list(llm_request.contents or [])
    for posicao in range(len(conteudos) - 1, -1, -1):
        conteudo = conteudos[posicao]
        if conteudo.role != "user":
            continue
        textos = [p.text for p in (conteudo.parts or []) if p.text]
        if not textos:
            continue
        junto = " ".join(textos)
        if PREAMBULO_DE_OUTRO_AGENTE in junto:
            continue
        return junto, conteudos[posicao + 1 :]
    return "", conteudos


def _ultima_resposta_de_tool(depois_do_pedido: list) -> tuple[str, dict] | None:
    """A última tool de domínio que respondeu nesta rodada.

    `transfer_to_agent` fica de fora: ela é roteamento, não resultado. Contá-la
    como resultado faria o especialista achar que já tem o que precisa no instante
    em que chega, e o pedido do morador morreria na transferência.
    """
    for conteudo in reversed(depois_do_pedido):
        for parte in reversed(conteudo.parts or []):
            se_resposta = parte.function_response
            if se_resposta is None or not se_resposta.name:
                continue
            if se_resposta.name == "transfer_to_agent":
                continue
            return se_resposta.name, dict(se_resposta.response or {})
    return None


def _area(frase: str) -> str | None:
    baixa = frase.lower()
    for identificador, apelidos in AREAS:
        if any(apelido in baixa for apelido in apelidos):
            return identificador
    return None


def _data(frase: str) -> str | None:
    encontrada = DATA.search(frase)
    return encontrada.group(0) if encontrada else None


def _capitulo(pergunta: str) -> str | None:
    baixa = pergunta.lower()
    for romano, palavras in CAPITULOS:
        if any(palavra in baixa for palavra in palavras):
            return romano
    return None


def _frase_da_tool(corpo: dict) -> str:
    if "mensagem" in corpo:
        return str(corpo["mensagem"])
    if "reservas" in corpo:
        reservas = corpo["reservas"]
        if not reservas:
            return "Você não tem nenhuma reserva ativa."
        return "Suas reservas: " + "; ".join(
            f"{r['codigo']} — {r['area']} em {r['data']}" for r in reservas
        )
    if "visitantes" in corpo:
        visitantes = corpo["visitantes"]
        if not visitantes:
            return "Você não tem visitas autorizadas."
        return "Suas visitas: " + "; ".join(
            f"{v['nome']} em {v['data']}" for v in visitantes
        )
    if "areas" in corpo and "erro" in corpo:
        return "Essa área não existe. As áreas são: " + ", ".join(
            str(a) for a in corpo["areas"]
        )
    if "disponivel" in corpo:
        estado = "livre" if corpo["disponivel"] else "ocupada"
        return f"A data {corpo['data']} está {estado} para {corpo['area']}."
    if "error" in corpo:
        return "Preciso de mais um dado para continuar: qual é a data?"
    return "Feito."


PALAVRAS_DE_REGULAMENTO = (
    "regulamento", "que horas", "é permitido", "pode ter", "posso ter", "norma"
)
PALAVRAS_DE_VISITANTES = ("visitante", "visita", "libera a entrada", "autoriz")
PALAVRAS_DE_RESERVAS = (
    "reserv", "cancel", "quadra", "salão", "salao", "churrasqueira", "área comum",
    "agenda", "disponib",
)


def _tem(frase: str, palavras: tuple[str, ...]) -> bool:
    baixa = frase.lower()
    return any(palavra in baixa for palavra in palavras)


def _dono(pedido: str) -> str:
    """Quem deve atender este pedido — uma decisão só, usada dos dois lados.

    O principal roteia por ela e cada especialista devolve o que não é dele pela
    mesma regra. Se as duas pontas discordassem, um pedido ficaria quicando entre
    o principal e o especialista para sempre.
    """
    if _tem(pedido, PALAVRAS_DE_REGULAMENTO):
        return "especialista_regulamento"
    if _tem(pedido, PALAVRAS_DE_VISITANTES):
        return "especialista_visitantes"
    if _tem(pedido, PALAVRAS_DE_RESERVAS):
        return "especialista_reservas"
    return "assistente_aurora"


class ModeloDeBancada(BaseLlm):
    model: str = "modelo-de-bancada"

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["modelo-de-bancada"]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        instrucao = ""
        if llm_request.config is not None and llm_request.config.system_instruction:
            instrucao = str(llm_request.config.system_instruction)
        encontrado = NOME_INTERNO.search(instrucao)
        agente = encontrado.group(1) if encontrado else "assistente_aurora"

        pedido, depois_do_pedido = _turno_atual(llm_request)
        resposta_de_tool = _ultima_resposta_de_tool(depois_do_pedido)

        if agente == "especialista_regulamento":
            # Roda isolado, na sessão descartável do AgentTool: não transfere.
            yield self._regulamento(pedido, resposta_de_tool)
            return

        if agente == "assistente_aurora":
            yield self._principal(pedido, resposta_de_tool)
            return

        if resposta_de_tool is None and _dono(pedido) != agente:
            # O Runner manda a mensagem seguinte para quem respondeu por último.
            # Quando ela não é deste especialista, ele devolve ao principal em vez
            # de responder de qualquer jeito — é o que um modelo bom faria.
            yield transferir("assistente_aurora")
            return

        if agente == "especialista_reservas":
            yield self._reservas(pedido, resposta_de_tool)
        elif agente == "especialista_visitantes":
            yield self._visitantes(pedido, resposta_de_tool)
        else:  # pragma: no cover - árvore de agentes mudou sem avisar a bancada
            yield texto("Não sei responder isso.")

    def _principal(self, pedido: str, resposta_de_tool) -> LlmResponse:
        if resposta_de_tool and resposta_de_tool[0] == "especialista_regulamento":
            corpo = resposta_de_tool[1]
            return texto(str(corpo.get("result") or corpo.get("response") or corpo))
        destino = _dono(pedido)
        if destino == "especialista_regulamento":
            return chamar("especialista_regulamento", request=pedido)
        if destino == "assistente_aurora":
            return texto("Posso ajudar com reservas, visitantes e o regulamento.")
        return transferir(destino)

    def _reservas(self, pedido: str, resposta_de_tool) -> LlmResponse:
        if resposta_de_tool:
            return texto(_frase_da_tool(resposta_de_tool[1]))

        baixa = pedido.lower()
        area = _area(pedido)
        data = _data(pedido)
        if "cancel" in baixa and area and data:
            return chamar("cancelar_reserva", area=area, data=data)
        if "reserv" in baixa and area and data:
            return chamar("reservar_area", area=area, data=data)
        return chamar("listar_minhas_reservas")

    def _visitantes(self, pedido: str, resposta_de_tool) -> LlmResponse:
        if resposta_de_tool:
            return texto(_frase_da_tool(resposta_de_tool[1]))

        data = _data(pedido)
        sem_ruido = re.sub(r"\b(Libera|Sou|Já|Quais|Autoriza)\b", "", pedido)
        nome = NOME_PROPRIO.search(sem_ruido)
        if nome and data and "libera" in pedido.lower():
            return chamar("autorizar_visitante", nome=nome.group(1), data=data)
        if nome and "libera" in pedido.lower():
            return chamar("autorizar_visitante", nome=nome.group(1))
        return chamar("listar_meus_visitantes")

    def _regulamento(self, pergunta: str, resposta_de_tool) -> LlmResponse:
        if resposta_de_tool and resposta_de_tool[0] == "ler_capitulo_do_regulamento":
            corpo = resposta_de_tool[1]
            if "texto" not in corpo:
                return texto("Isso não consta no regulamento interno.")
            return texto(_linha_pertinente(corpo["texto"], pergunta))

        capitulo = _capitulo(pergunta)
        if capitulo is None:
            return texto("Isso não consta no regulamento interno.")
        return chamar("ler_capitulo_do_regulamento", capitulo=capitulo)


def _linha_pertinente(capitulo: str, pergunta: str) -> str:
    """Escolhe a frase do capítulo que responde a pergunta, e devolve só ela.

    Devolver o capítulo inteiro aqui seria o modelo, e não o código, violando a
    Garantia 4 — mas mesmo assim o texto ficaria na sessão descartável do
    `AgentTool`. O recorte existe porque é o que um modelo bom faria.
    """
    palavras = {p for p in re.findall(r"\w{5,}", pergunta.lower())}
    melhor, pontos = "", 0
    for linha in capitulo.splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("##"):
            continue
        atual = sum(1 for palavra in palavras if palavra in limpa.lower())
        if atual > pontos:
            melhor, pontos = limpa, atual
    return melhor or "Isso não consta no regulamento interno."
