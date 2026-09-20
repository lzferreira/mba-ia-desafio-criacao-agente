"""As tools do assistente. Nenhuma delas aceita um apartamento.

Garantia 2: não existe parâmetro de apartamento em assinatura nenhuma, então não
existe valor que o modelo possa escolher e que alguém precise lembrar de validar
depois. O número sai de `tool_context.state`, escrito uma única vez na criação da
sessão.

Garantia 1: reserva com taxa e autorização de visita só gravam com uma
`ToolConfirmation` confirmada em mãos. A exigência aparece duas vezes de propósito
— em `require_confirmation`, que é o que faz o ADK emitir a pendência e parar, e
de novo no corpo, que é o que recusa a gravação se a execução chegar lá sem ela.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from . import dominio, regulamento
from .aplicacao import Aplicacao

CHAVE_DO_APARTAMENTO = "apartamento"


class SessaoSemApartamento(RuntimeError):
    """Nenhuma tool de domínio roda sem o apartamento fixado na criação da sessão."""


def apartamento_da_sessao(tool_context: ToolContext) -> str:
    numero = tool_context.state.get(CHAVE_DO_APARTAMENTO)
    if not numero:
        raise SessaoSemApartamento(
            "A sessão não tem apartamento no state; nenhuma tool pode continuar."
        )
    return str(numero)


def _confirmada(tool_context: ToolContext) -> bool:
    confirmacao = getattr(tool_context, "tool_confirmation", None)
    return bool(confirmacao and confirmacao.confirmed)


def construir_ferramentas(aplicacao: Aplicacao) -> dict[str, list[FunctionTool]]:
    """Fecha as tools sobre a aplicação e as agrupa por especialista."""

    def consultar_areas() -> dict:
        """Lista as áreas comuns do condomínio, com o identificador e a taxa de cada uma."""
        with aplicacao.banco() as conexao:
            return dominio.areas_disponiveis(conexao)

    def consultar_disponibilidade(area: str, data: str) -> dict:
        """Diz se uma área está livre ou ocupada numa data, sem dizer de quem é a reserva.

        Args:
            area: o identificador da área, como `salao-de-festas`.
            data: a data no formato AAAA-MM-DD.
        """
        with aplicacao.banco() as conexao:
            return dominio.disponibilidade(conexao, area, data)

    def listar_minhas_reservas(tool_context: ToolContext) -> dict:
        """Lista as reservas ativas do apartamento do morador que está na conversa."""
        with aplicacao.banco() as conexao:
            return dominio.minhas_reservas(conexao, apartamento_da_sessao(tool_context))

    def exige_confirmacao_de_reserva(**argumentos: Any) -> bool:
        """Decide pela taxa da área, lida no banco, se a reserva gera cobrança.

        Área desconhecida devolve `False` e nada acontece por isso: o corpo da tool
        recusa a gravação antes de qualquer escrita, então não há caminho em que
        um identificador inventado pelo modelo vire reserva sem confirmação.
        """
        area = argumentos.get("area")
        if not area:
            return False
        with aplicacao.banco() as conexao:
            return dominio.exige_cobranca(conexao, str(area))

    def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
        """Reserva uma área comum para o apartamento do morador que está na conversa.

        Args:
            area: o identificador da área, como `salao-de-festas`.
            data: a data no formato AAAA-MM-DD.
        """
        apartamento = apartamento_da_sessao(tool_context)
        with aplicacao.banco() as conexao:
            if dominio.exige_cobranca(conexao, area) and not _confirmada(tool_context):
                return {
                    "ok": False,
                    "motivo": "sem_confirmacao",
                    "mensagem": (
                        "Essa reserva gera cobrança e só executa depois da"
                        " confirmação respondida pelo aplicativo."
                    ),
                }
            return dominio.reservar(conexao, apartamento, area, data)

    def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
        """Cancela uma reserva do apartamento do morador que está na conversa.

        Args:
            area: o identificador da área, como `quadra`.
            data: a data no formato AAAA-MM-DD.
        """
        apartamento = apartamento_da_sessao(tool_context)
        with aplicacao.banco() as conexao:
            return dominio.cancelar(conexao, apartamento, area, data)

    def listar_meus_visitantes(tool_context: ToolContext) -> dict:
        """Lista as visitas autorizadas do apartamento do morador que está na conversa."""
        with aplicacao.banco() as conexao:
            return dominio.meus_visitantes(conexao, apartamento_da_sessao(tool_context))

    def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
        """Autoriza a entrada de um visitante no apartamento do morador da conversa.

        Args:
            nome: o nome de quem vai entrar.
            data: a data da visita, no formato AAAA-MM-DD.
        """
        apartamento = apartamento_da_sessao(tool_context)
        if not _confirmada(tool_context):
            return {
                "ok": False,
                "motivo": "sem_confirmacao",
                "mensagem": (
                    "Autorizar visitante libera a entrada de alguém no prédio e só"
                    " executa depois da confirmação respondida pelo aplicativo."
                ),
            }
        with aplicacao.banco() as conexao:
            return dominio.autorizar_visitante(conexao, apartamento, nome, data)

    def listar_capitulos_do_regulamento() -> dict:
        """Lista a numeração e o título dos capítulos do regulamento interno."""
        return {
            "capitulos": regulamento.listar(
                aplicacao.configuracao.caminho_do_regulamento
            )
        }

    def ler_capitulo_do_regulamento(capitulo: str) -> dict:
        """Lê um único capítulo do regulamento interno.

        Args:
            capitulo: a numeração romana do capítulo, como `IV`, ou o título dele.
        """
        encontrado = regulamento.ler(
            aplicacao.configuracao.caminho_do_regulamento, capitulo
        )
        if encontrado is None:
            return {
                "erro": "capitulo_inexistente",
                "capitulos": regulamento.listar(
                    aplicacao.configuracao.caminho_do_regulamento
                ),
            }
        return {
            "capitulo": encontrado.numero,
            "titulo": encontrado.titulo,
            "texto": encontrado.texto,
        }

    return {
        "reservas": [
            FunctionTool(consultar_areas),
            FunctionTool(consultar_disponibilidade),
            FunctionTool(listar_minhas_reservas),
            FunctionTool(
                reservar_area, require_confirmation=exige_confirmacao_de_reserva
            ),
            FunctionTool(cancelar_reserva),
        ],
        "visitantes": [
            FunctionTool(listar_meus_visitantes),
            FunctionTool(autorizar_visitante, require_confirmation=True),
        ],
        "regulamento": [
            FunctionTool(listar_capitulos_do_regulamento),
            FunctionTool(ler_capitulo_do_regulamento),
        ],
    }


# As tools que gravam cobrança ou liberam acesso. A lista existe para a prova do
# check C29 poder varrer o conjunto inteiro em vez de amostrar.
TOOLS_QUE_EXIGEM_CONFIRMACAO = {"reservar_area", "autorizar_visitante"}
