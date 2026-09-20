# Assistente do Residencial Aurora

Assistente de condomínio construído com **Google ADK**, exposto por uma API em
`http://localhost:8000`. O morador conversa por chat para reservar áreas comuns,
cancelar as próprias reservas, autorizar visitantes e tirar dúvidas do regulamento
interno.

O princípio do projeto cabe numa frase: **o modelo decide o caminho, o código decide
o que é permitido.** Nenhuma regra crítica mora no prompt — nenhuma mensagem, por
melhor escrita que seja, consegue furar uma delas.

## Arquitetura

Quatro agentes, em `assistente/agentes.py`, e duas formas de acionar especialista.
A escolha entre as duas não é estilo: ela decide se um pedido de confirmação chega
à sessão do morador e se o texto do regulamento entra no histórico.

| Agente | Responsabilidade | Como é acionado | Por quê |
| --- | --- | --- | --- |
| `assistente_aurora` | Fala com o morador e encaminha o trabalho. Não tem tool de domínio própria. | É o `root_agent` do `App`. | Um só ponto de entrada mantém o roteamento num lugar e deixa cada especialista com um conjunto pequeno de tools. |
| `especialista_reservas` | Consulta áreas e agenda, reserva e cancela para o apartamento da sessão. | `sub_agent` do principal — transferência (`transfer_to_agent`). | Ele pede confirmação, e um pedido de confirmação só chega à sessão do morador se o agente estiver rodando dentro dela. Transferência mantém o agente na sessão principal; `AgentTool` não. |
| `especialista_visitantes` | Autoriza a entrada de visitantes e lista as visitas do apartamento da sessão. | `sub_agent` do principal — transferência. | Mesmo motivo: autorizar visita libera acesso, então para em confirmação. |
| `especialista_regulamento` | Responde dúvidas do regulamento lendo o capítulo pertinente. | `AgentTool` dentro de `tools` do principal — chamado como tool, sem transferência. | `AgentTool` roda o agente num `Runner` próprio com `InMemorySessionService` descartável (`tools/agent_tool.py:264-268` do ADK 2.9.2). O capítulo que ele lê fica naquela sessão descartável e nunca entra nos eventos do morador. É o isolamento que sustenta a Garantia 4. |

As tools vivem em `assistente/ferramentas.py` e as regras em `assistente/dominio.py`.
Nenhuma tool de domínio recebe o apartamento como argumento: o número sai de
`tool_context.state`, escrito uma única vez na criação da sessão.

O armazenamento são dois SQLite separados, em `var/`:

- `var/condominio.db` — `apartamentos`, `areas`, `reservas` e `visitantes`, semeado a
  partir de `dados/` (`assistente/armazenamento.py`). Os arquivos de `dados/` são só
  lidos, nunca escritos.
- `var/sessoes.db` — as sessões do ADK, por `SqliteSessionService`. O serviço de
  sessão é dono do schema dele, e separar os dois é o que deixa a restauração apagar
  as sessões sem tocar no estado do condomínio.

A montagem acontece num lugar só, `assistente/aplicacao.py::construir_api`, que
prepara o banco, monta a árvore de agentes e devolve a API já pronta.

```
morador ──HTTP──> assistente/api.py ──> Runner + App(is_resumable=True)
                       │                      │
                       │                      ├── assistente_aurora
                       │                      │      ├─ transfere ─> especialista_reservas ──┐
                       │                      │      ├─ transfere ─> especialista_visitantes ┤
                       │                      │      └─ chama tool ─> especialista_regulamento (sessão descartável)
                       │                      │                                              │
                       └── rotas de verificação ─────────────────> var/condominio.db <───────┘
```

## Garantias

Cada uma está no código e cada uma é conferida por uma prova executável, listada ao
final desta seção.

### Garantia 1 — cobrança ou acesso só com confirmação

**Onde:** `assistente/ferramentas.py` (`exige_confirmacao_de_reserva`, `reservar_area`,
`autorizar_visitante`, `_confirmada`), `assistente/pendencias.py` (`derivar`,
`encontrar`) e `assistente/api.py` (rota `POST /sessoes/{id}/confirmacoes`).

A exigência aparece em três lugares, e nenhum deles é o prompt:

1. `FunctionTool(reservar_area, require_confirmation=exige_confirmacao_de_reserva)` —
   a decisão sai da **taxa da área lida no banco**, não do texto da mensagem.
   `FunctionTool(autorizar_visitante, require_confirmation=True)` — liberar acesso
   sempre confirma. Quando a confirmação é exigida e não existe, o ADK emite uma
   `adk_request_confirmation` e a execução para ali.
2. O corpo das duas tools checa `tool_context.tool_confirmation.confirmed` antes de
   qualquer escrita e recusa sem ela. É a segunda tranca: mesmo que a primeira fosse
   removida por engano, nada é gravado.
3. A rota de confirmações é a **única** porta. Ela deriva as pendências dos eventos
   da sessão e recusa com `409`, antes de chamar o Runner, qualquer `id` que não
   esteja pendente ali — inclusive um já respondido e um pendente em outra sessão.

Não depende do modelo porque "já estou confirmando aqui" é texto: ele não vira uma
`functionResponse` de nome `adk_request_confirmation` na sessão, que é a única coisa
que o ADK aceita como confirmação. E a pendência é **derivada dos eventos**, não de
uma tabela: um `id` já respondido deixa de estar pendente porque a resposta virou
evento, o que dá a execução única e o `409` de graça.

**Sobre a retomada.** Quando a rota entrega a resposta ao `Runner`, quem escolhe o
agente que vai retomar é `find_agent_to_run`. O `App` sobe com
`ResumabilityConfig(is_resumable=True)` (`assistente/aplicacao.py`), que é o que faz
esse roteamento olhar o **autor** da `functionCall` original. Vale registrar o que
medimos: nesta árvore o desligado também acertaria, mas por acidente — a varredura de
eventos cai no especialista porque ele respondeu por último e pode transferir de volta
ao pai. Bastaria bloquear essa transferência para o desligado devolver o agente raiz e
a confirmação ser abandonada em silêncio. `testes/unidade/test_retomada.py` demonstra
os dois sentidos, e é por isso que a linha fica.

### Garantia 2 — cada sessão pertence a um apartamento

**Onde:** `assistente/aplicacao.py` (`Aplicacao.criar_sessao`),
`assistente/ferramentas.py` (`apartamento_da_sessao`) e `assistente/dominio.py`
(`disponibilidade`, `cancelar`).

O apartamento entra no `state` uma única vez, na criação da sessão, e nada o
reescreve depois. **Nenhuma tool de domínio declara parâmetro de apartamento** —
`inspect.signature` de cada uma das nove tools registradas não tem um. Não existe
argumento escolhido pelo modelo para alguém lembrar de validar depois; a tool lê
`tool_context.state["apartamento"]` e levanta `SessaoSemApartamento` se não achar.

A consulta de agenda olha a agenda inteira, como o enunciado permite, e devolve só
`disponivel: true/false` — nunca o código nem o apartamento do dono. Cancelar reserva
alheia e cancelar uma que não existe respondem a **mesma frase**, de propósito:
distinguir os dois contaria que a reserva do vizinho existe.

### Garantia 3 — nada se perde no reinício

**Onde:** `assistente/aplicacao.py` (`SqliteSessionService`, `construir_api`) e
`assistente/armazenamento.py` (`preparar`).

As sessões vão para `var/sessoes.db` e os dados do condomínio para
`var/condominio.db`. Nada de conversa ou de pendência vive em memória do processo: a
lista de `confirmacoes_pendentes` é recalculada dos eventos a cada resposta, então
uma pendência aberta antes do reinício continua aprovável depois dele.

Não depende do modelo porque não há nada a lembrar: o estado está em disco e a
pendência é uma função pura dos eventos.

### Garantia 4 — o regulamento é consultado, não carregado

**Onde:** `assistente/agentes.py` (`especialista_regulamento` dentro de `AgentTool`,
`INSTRUCAO_DO_PRINCIPAL`), `assistente/regulamento.py` (`listar`, `ler`) e
`assistente/ferramentas.py` (`ler_capitulo_do_regulamento`).

Duas coisas, ambas estruturais:

- A instrução do agente principal não contém nenhum trecho do regulamento — a prova
  varre as centenas de linhas longas do arquivo e confere que nenhuma aparece nela.
- O especialista de regulamento é `AgentTool`, então roda num `Runner` próprio com
  sessão em memória descartável. O capítulo que ele lê fica lá; o que volta para a
  sessão do morador é a resposta. A prova faz o especialista ler **de propósito** dois
  capítulos de outros assuntos (VIII, animais; XI, garagem) antes de achar o certo, e
  mostra que nem assim o texto deles chega aos eventos.

E a leitura é recortada: `regulamento.ler` devolve um capítulo, que começa no próprio
título e termina antes do próximo. Não existe função que devolva o arquivo inteiro.

### Garantia 5 — dois moradores, uma reserva

**Onde:** `assistente/armazenamento.py` (`ESTRUTURA`, `gravar_reserva`) e
`assistente/dominio.py` (`reservar`).

```sql
CREATE UNIQUE INDEX IF NOT EXISTS reservas_area_data_ativa
    ON reservas(area, data) WHERE ativa = 1;
```

`gravar_reserva` abre `BEGIN IMMEDIATE`, insere e deixa o **commit** decidir. Quando o
índice recusa, a exceção vira `DataIndisponivel` e `dominio.reservar` a traduz numa
resposta normal — nunca um 5xx.

Não depende de conferência prévia: `dominio.reservar` **não consulta a agenda antes de
gravar**. A tool `consultar_disponibilidade` existe como conveniência para o morador e
não participa da gravação. Entre duas aprovações simultâneas, quem separa as duas é o
banco, no instante do write.

O índice é parcial (`WHERE ativa = 1`), então cancelar libera a data de novo — e como
`codigo` é `PRIMARY KEY` da tabela inteira e cancelar é `UPDATE ... SET ativa = 0` e
nunca `DELETE`, o código de uma reserva cancelada nunca volta a ser usado.

### As provas

| Garantia | Provas |
| --- | --- |
| 1 | `testes/fio/test_confirmacao.py`, `testes/unidade/test_ferramentas.py` |
| 2 | `testes/unidade/test_ferramentas.py`, `testes/fio/test_conversa.py`, `testes/fio/test_reserva.py` |
| 3 | `testes/fio/test_persistencia.py` |
| 4 | `testes/fio/test_regulamento.py`, `testes/unidade/test_agentes.py`, `testes/unidade/test_regulamento.py` |
| 5 | `testes/unidade/test_armazenamento.py`, `testes/fio/test_reserva.py` |

`roteiro/avaliador.py` replica os 15 passos do fluxo do avaliador contra a API de
pé, incluindo o reinício do passo 13 e a disputa do passo 14, e sai com código
diferente de zero na primeira verificação que falhar.

## Como rodar

### Pré-requisitos

- Python 3.12 ou superior.
- [uv](https://docs.astral.sh/uv/).
- Uma chave do [Google AI Studio](https://aistudio.google.com/apikey).

Nenhum serviço externo: o armazenamento é SQLite em arquivo, criado em `var/`.

### Variáveis do `.env`

```bash
cp .env.example .env
```

| Variável | Obrigatória | Para quê |
| --- | --- | --- |
| `GOOGLE_API_KEY` | sim | A chave do Google AI Studio. Sem ela a API não sobe: o processo encerra nomeando a variável, antes de abrir a porta 8000. |
| `GEMINI_MODEL` | não | O modelo usado pelos quatro agentes. Em branco, `gemini-2.5-flash`. |

### Instalar

```bash
uv sync
```

### Restaurar os dados iniciais

```bash
uv run aurora-restaurar
```

Recria `var/condominio.db` a partir de `dados/` e apaga `var/sessoes.db`. Roda sem
argumentos, não precisa de chave e pode ser repetido: o estado final é sempre o dos
arquivos de `dados/`, que nunca são escritos.

### Subir a API

```bash
uv run aurora-api
```

A API responde em `http://localhost:8000`. Se o banco do condomínio não existir, ele
é semeado antes de a primeira requisição ser atendida.

```bash
curl -s localhost:8000/apartamentos/101/reservas
# [{"codigo":"RSV-1377","area":"quadra","data":"2030-03-09"}]
```

### Conferir o fluxo inteiro

Com o `.env` preenchido e a API **parada** (o roteiro sobe e derruba a API por conta
própria):

```bash
uv run python -m roteiro.avaliador
```

### Rodar as provas

```bash
uv run pytest
```

## Contrato da API

| Rota | Corpo | Resposta |
| --- | --- | --- |
| `POST /sessoes` | `{"apartamento": "101"}` | `201 {"session_id": "..."}`; `404` se o apartamento não existe |
| `POST /sessoes/{id}/mensagens` | `{"texto": "..."}` | `200 {"resposta": "...", "confirmacoes_pendentes": [{"id", "acao", "detalhes"}]}` |
| `POST /sessoes/{id}/confirmacoes` | `{"id": "...", "confirmado": true}` | `200` no mesmo formato; `409` se o id não está pendente nesta sessão |
| `GET /sessoes/{id}/eventos` | — | `200` com todos os eventos, em ordem, completos |
| `GET /apartamentos/{numero}/reservas` | — | `200 [{"codigo", "area", "data"}]` |
| `GET /apartamentos/{numero}/visitantes` | — | `200 [{"nome", "data"}]` |

As rotas com `{id}` respondem `404` quando a sessão não existe. `resposta` vem como
string vazia quando a execução parou esperando confirmação, e
`confirmacoes_pendentes` é `[]` quando não há pendência. As rotas de verificação leem
o banco direto, sem passar pelo modelo.
