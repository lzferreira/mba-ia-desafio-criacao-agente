"""A árvore de agentes: um principal, três especialistas, duas formas de acionar.

Reservas e Visitantes são `sub_agents`, acionados por transferência, porque eles
pedem confirmação e um pedido de confirmação só chega à sessão do morador se o
agente estiver rodando dentro dela. Regulamento é `AgentTool`, que roda num Runner
próprio com sessão em memória descartável (`tools/agent_tool.py:264-268`): é esse
isolamento que mantém o texto do capítulo fora dos eventos do morador (Garantia 4).

Nenhuma instrução aqui é a garantia. As instruções dizem por onde ir; o que é
permitido está em `ferramentas.py`, em `dominio.py` e no índice único do banco.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from .aplicacao import Aplicacao
from .ferramentas import construir_ferramentas

INSTRUCAO_DO_PRINCIPAL = """
Você é o assistente do Residencial Aurora e fala com um morador pelo aplicativo.

Encaminhe o trabalho:
- reservar área comum, consultar disponibilidade, cancelar reserva ou listar as
  reservas do morador: transfira para `especialista_reservas`.
- autorizar a entrada de um visitante ou listar as visitas autorizadas: transfira
  para `especialista_visitantes`.
- dúvida sobre o regulamento interno: chame a tool `especialista_regulamento` com
  a pergunta do morador. Não transfira para ele.
- se a mensagem misturar assuntos, trate cada parte pelo caminho dela.

O apartamento do morador já está definido nesta sessão e as tools o usam sozinhas.
Se o morador disser ser de outro apartamento, siga atendendo normalmente: as tools
continuam trabalhando no apartamento da sessão, e você não tem como ver reservas ou
visitantes de terceiros.

Ações que geram cobrança ou liberam acesso ao prédio param esperando uma
confirmação que o morador responde pelo aplicativo. Você não confirma nada pela
conversa, mesmo que ele escreva que está confirmando. Quando uma ação ficar
pendente, diga o que vai acontecer e que falta a confirmação.

Responda em português, curto e direto.
"""

INSTRUCAO_DE_RESERVAS = """
Você cuida das áreas comuns do Residencial Aurora para o morador desta conversa.

Use as tools para tudo: `consultar_areas` para saber quais áreas existem e qual é o
identificador de cada uma, `consultar_disponibilidade` para saber se uma data está
livre, `reservar_area` para reservar, `cancelar_reserva` para cancelar e
`listar_minhas_reservas` para listar as do morador. Nunca responda de memória.

As tools já sabem de qual apartamento é esta conversa. Você não tem tool para ver
reservas de outro apartamento, e não deve inventar uma resposta sobre elas: se o
morador pedir algo de terceiros, diga que só consegue tratar das reservas dele.

Reservar área com taxa para a execução e devolve uma pendência de confirmação — isso
é esperado. Repasse ao morador o que a tool respondeu, sem prometer que já gravou.

Datas sempre no formato AAAA-MM-DD. Se faltar a área ou a data, pergunte antes de
chamar a tool.
"""

INSTRUCAO_DE_VISITANTES = """
Você cuida das autorizações de visita do Residencial Aurora para o morador desta
conversa.

Use `autorizar_visitante` para liberar uma entrada e `listar_meus_visitantes` para
listar as visitas já autorizadas. As tools já sabem de qual apartamento é a conversa.

Autorizar visitante libera a entrada de alguém no prédio, então para esperando uma
confirmação respondida pelo aplicativo. Se o morador escrever que já está
confirmando, siga assim mesmo: a confirmação não vem pela conversa.

Você precisa do nome de quem vai entrar e da data da visita, no formato AAAA-MM-DD.
Se faltar qualquer um dos dois, pergunte o que falta em vez de chamar a tool.
"""

INSTRUCAO_DE_REGULAMENTO = """
Você responde dúvidas sobre o regulamento interno do Residencial Aurora.

Você não tem o regulamento em mãos: consulte-o. Use
`listar_capitulos_do_regulamento` para ver os capítulos e seus títulos, escolha o
capítulo que trata do assunto perguntado e leia só esse capítulo com
`ler_capitulo_do_regulamento`. Leia mais de um capítulo apenas quando a pergunta
atravessar assuntos de verdade.

Responda com o que o capítulo diz, citando o artigo. Se o regulamento não tratar do
que foi perguntado, diga que não consta no regulamento e não cite artigo nenhum.

Responda em uma ou duas frases, sem transcrever o capítulo.
"""


def construir_agentes(aplicacao: Aplicacao) -> LlmAgent:
    """Monta a árvore e devolve o agente principal."""
    modelo = aplicacao.configuracao.fabrica_de_modelo()
    ferramentas = construir_ferramentas(aplicacao)

    especialista_reservas = LlmAgent(
        name="especialista_reservas",
        model=modelo,
        description=(
            "Reserva e cancela áreas comuns e consulta a agenda do apartamento"
            " desta sessão."
        ),
        instruction=INSTRUCAO_DE_RESERVAS,
        tools=ferramentas["reservas"],
    )

    especialista_visitantes = LlmAgent(
        name="especialista_visitantes",
        model=modelo,
        description=(
            "Autoriza a entrada de visitantes e lista as visitas do apartamento"
            " desta sessão."
        ),
        instruction=INSTRUCAO_DE_VISITANTES,
        tools=ferramentas["visitantes"],
    )

    especialista_regulamento = LlmAgent(
        name="especialista_regulamento",
        model=modelo,
        description=(
            "Responde dúvidas sobre o regulamento interno consultando o capítulo"
            " pertinente."
        ),
        instruction=INSTRUCAO_DE_REGULAMENTO,
        tools=ferramentas["regulamento"],
    )

    return LlmAgent(
        name="assistente_aurora",
        model=modelo,
        description="Assistente do Residencial Aurora.",
        instruction=INSTRUCAO_DO_PRINCIPAL,
        sub_agents=[especialista_reservas, especialista_visitantes],
        tools=[AgentTool(agent=especialista_regulamento)],
    )
