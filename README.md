# Camoufox Automations

Hub de automações de web scraping e gestão de painéis, construído para ser
operado **por humanos e por agentes de IA** (Hermes, OpenCode, MCP clients).
Navegador furtivo (Camoufox), ELT em SQLite, CLI Typer e MCP FastMCP —
uma pasta por site automatizado.

> **Você é uma IA lendo isto?** Comece pela seção [Regras de Ouro](#regras-de-ouro-para-ia)
> e pela [Tabela de Automações](#inventário-de-automações). Elas resumem o que
> você pode fazer, como fazer e o que **nunca** fazer.

---

## Regras de Ouro para IA

Este projeto manipula um **painel de produção com clientes reais** (Sigma
IPTV). A segurança não é sugerida — é arquitetural:

1. **Read-only é o padrão.** Escrita só por método nomeado e explícito
   (`create_customer`, `update_customer`...). Não existe método genérico de
   POST/PUT/DELETE na API client — e não crie um.
2. **Guard antes de explorar.** Todo script exploratório instala
   `explore/_guard.py` (aborta POST/PUT/PATCH/DELETE no nível do browser).
   Mutações intencionais usam o guardião de URL do `07` (allowlist de ID).
3. **Snapshot antes e depois de qualquer escrita.**
   `06_customers_snapshot.py` + diff. Zero divergências além do cliente teste
   é a definição de sucesso.
4. **Só clientes de teste.** Nomes `zz_test_*` inconfundíveis, criados e
   **excluídos** no mesmo run. Nunca mutar cliente real — nem "só um pouquinho".
5. **Destructive pede flag.** `sigma-customer-delete` exige `--yes`; MCP
   `excluir_cliente_sigma` exige `confirmar=True`. Não contorne.
6. **Endpoints em blocklist permanente** (não usar sem aprovação explícita do
   dono): `mass-delete`, `move`, `migration`, BotBot/mensagens, rotas de
   financeiro. O inventário os marca como `blocked`.
7. **PII nunca sai do `out/`.** Snapshots, capturas e sessões ficam em
   diretórios gitignored. Nunca commite token, cookie ou dado de cliente.

### Fatos técnicos que vão te poupar horas (já descobertos à moda antiga)

| Fato | Detalhe |
|---|---|
| Transporte | Cloudflare bloqueia `requests` (fingerprint TLS) e o `context.request` do Playwright (DNS morre no Node). **Único caminho: `fetch` dentro da página** via `page.evaluate` — usa o DoH do browser + TLS real do Firefox. `open_client()` entrega isso pronto. |
| DNS | A máquina não resolve `*.sigma.st` (só via DoH). O browser já nasce com Google DoH (`core/browser.py`); o motor `requests` tem adapter DoH embutido (só serve p/ testes). |
| Headers de mutação | Sem `Accept: application/json` + `X-Requested-With: XMLHttpRequest` o Laravel responde validação com **302→HTML status 200** (parece sucesso, não fez nada). Já estão no `_AXIOS_HEADERS`. |
| Paginação | O param `per_page` (snake_case) é **silenciosamente ignorado**; use `perPage` (camelCase), cap 100. |
| Expiração | Campo canônico é `expires_at` ISO (`2026-11-04T02:59:59.000000Z` — painel fixo UTC-3; 02:59:59Z = 23:59:59 local). `expiry_date`/`due_date` são legados. |
| IDs | São **strings** do painel (`2YD0JXlv1Q`), não ints. |
| Sessão | Token Laravel `id\|hash`, sem expiração client-side; validade = `GET /api/auth/me` 200. Reuso automático via `ensure_logged_page`. |
| Proxy | `SIGMA_PROXY` (ex. `socks5://100.x.y.z:1080`) vira o proxy padrão de todo acesso Sigma (`open_client`/`ensure_logged_page`). Útil p/ rota dedicada (Tailscale+microsocks). **`cf_clearance` é IP-bound**: escolha o caminho ANTES do primeiro login e não troque — senão refaça `sigma-login --save`. |
| Soft delete | `DELETE /customers/{id}` é soft (volta `deleted_at`); restore existe mas nunca foi testado. |
| Listagem | `GET /customers/{id}` **não existe** (404 HTML). Para detalhes: `resync` ou buscar na lista paginada (`find_customer`). |
| VPS/máquina | Shell wrapper `rtk` pede `bash -c "..."` para comandos encadeados; git identity inline nos commits; `graphify` reconstrói o grafo a cada commit (hook). |

---

## Estrutura (uma pasta por site)

```
core/
  automations.py        # INVENTÁRIO — fonte única (CLI/MCP/README leem daqui)
  browser.py            # Camoufox headless virtual + Google DoH hardcoded
  database.py           # SQLite: raw_snapshots, products, panel_entities (UPSERT)
  sigma/                # SITE: painel Sigma IPTV (lideriptv.sigma.st)
    auth.py             #   login, sessão, reuso/validade de token
    api.py              #   SigmaApiClient (GET whitelist + 4 mutações nomeadas)
    scraper.py          #   sync_* (ELT: fetch → raw → panel_entities)
    explore/            #   scripts de descoberta (dev, mantêm o mapa vivo)
      _guard.py         #     kill switch de rede (aborta mutação)
      01..07_*.py       #     sessão, mapa, crawl, probe, crudmap, snapshot, lifecycle
      PANEL_MAP.md      #     MAPA CANÔNICO do painel (endpoints, schema, descobertas)
      out/              #     capturas (GITIGNORED — PII)
  ecommerce_x/          # SITE: placeholder httpbin (padrão para o próximo site)
    scraper.py
    explore/
interfaces/
  cli/                  # Typer: __init__ (hub+automations), sigma.py, ecommerce.py
  mcp/                  # FastMCP: server.py (hub), sigma.py, ecommerce.py
tests/                  # pytest (20 testes; sem deps novas — fakes na mão)
main.py                 # `main.py` = CLI | `main.py mcp` = servidor MCP
```

## Setup

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/camoufox fetch                  # baixa o browser (~1x)
pytest tests/                            # deve passar 92/92
# credenciais (env OU sigma_accounts.json — ver seção Multi-conta):
export SIGMA_USERNAME=... SIGMA_PASSWORD=...
venv/bin/python main.py sigma-login --save   # gera sigma_session.json (gitignored)
```

## Multi-conta (várias credenciais para o mesmo painel)

Credenciais em `sigma_accounts.json` (raiz, gitignored) — a ordem do arquivo é
a prioridade:

```json
[
  {"username": "MarcioNPTV", "password": "..."},
  {"username": "backup_ads", "password": "..."}
]
```

**Qual conta está ativa** (resolvida a cada comando, sem estado em memória):

```
env SIGMA_ACCOUNT  >  .sigma_last_good (ponteiro)  >  primeira do arquivo
```

- `SIGMA_ACCOUNT=backup_ads main.py sigma-status` — override por processo, **não
  toca o ponteiro** (feito para cron/Hermes forçarem uma conta).
- Cada conta tem sua própria sessão: a primária em `sigma_session.json`
  (compatibilidade com tudo que já existia), as demais em
  `.sigma_session_<usuario>.json` (gitignored).

**CLI:**

```bash
venv/bin/python main.py sigma-account list          # nome | sessão ✔ | ← ativa
venv/bin/python main.py sigma-account add NOME      # cadastra (senha oculta)
venv/bin/python main.py sigma-account use NOME      # ponteiro; próximo comando usa
venv/bin/python main.py sigma-account remove NOME
venv/bin/python main.py sigma-login --user NOME     # login fresco dessa conta
```

**MCP:** `listar_contas_sigma()` (conta ativa + quem tem sessão salva, nunca
senhas) e `trocar_conta_sigma(username)` (escreve o ponteiro e valida no painel
via `/api/auth/me` — pode demorar ~1min se a conta estiver sem sessão).

Comportamento: failover de sessão acontece só no boot (tenta a ativa, depois as
demais — trocar de conta não força novo login se a sessão dela está boa);
relogin usa somente a conta ativa. `SIGMA_PROXY` vale para todas (cf_clearance
é IP-bound: todas as contas devem sair pelo mesmo egress). Sem o arquivo de
contas, tudo funciona como antes (env creds → modo legado).

## Como a IA deve operar (receita)

1. **Descobrir o que existe** → `main.py automations` (ou tool MCP
   `listar_automacoes`). Status `ok` = pode usar direto; `planned` = endpoint
   mapeado, falta fiação; `blocked` = precisa de aprovação humana explícita.
2. **Ler o mapa antes de tocar** → `core/sigma/explore/PANEL_MAP.md` tem
   endpoints, schemas e pegadinhas por seção do painel.
3. **Sincronizar dados** → `sigma-sync --what all --pages 5` (banco local
   sempre; UPSERT idempotente, pode rodar quantas vezes quiser).
4. **Criar/editar/excluir cliente** → comandos `sigma-customer-*` / tools MCP.
   Antes: snapshot (06). Depois: snapshot + diff = zero. Cliente de teste só
   com nome `zz_test_*`, excluído no mesmo run.
5. **Explorar área nova do painel** → seguir o padrão dos exploradores:
   guard ligado, blocklist de seções sensíveis, `--max` pequeno, um commit por
   script, achados documentados no PANEL_MAP.md.
6. **Adicionar automação** → núcleo em `core/<site>/`, comando em
   `interfaces/cli/<site>.py`, tool em `interfaces/mcp/<site>.py`, teste em
   `tests/`, **e uma linha no `core/automations.py`**. Commit pequeno por passo.

## Inventário de automações

Fonte viva: `core/automations.py` (este espelho pode envelhecer; o comando
`automations` nunca envelhece). Resumo:

| Status | Qtd | Exemplos |
|---|---|---|
| `ok` | 21 | login (multi-conta), sync (customers/expiring/dashboard/resellers/statistics/servers+packages/all), status, CRUD de cliente (create/update/delete/resync), 7 exploradores, demo ecommerce |
| `planned` | 5 | notices, top10, ai-analysis, export CSV, restore |
| `blocked` | 3 | BotBot/mensagens, bulk (mass-delete/move/migration), financeiro |

## Interfaces

**CLI** (`venv/bin/python main.py <comando>`): `automations`, `sigma-login
[--user NOME]`, `sigma-account list|use|add|remove`, `sigma-sync`,
`sigma-status`, `sigma-servers-packages`,
`sigma-customer-create|update|delete|resync`, `sync-item`. MCP (`main.py mcp`):
`listar_automacoes`, `login_sigma`, `sincronizar_sigma`, `status_sigma`,
`criar_cliente_sigma`, `editar_cliente_sigma`, `excluir_cliente_sigma`,
`resync_cliente_sigma`, `listar_pacotes_sigma`, `buscar_cliente_sigma`,
`listar_clientes_sigma`, `listar_contas_sigma`, `trocar_conta_sigma`,
`consultar_e_sincronizar_produto`.

### Paridade CLI ↔ MCP

| Ação | CLI | MCP |
|---|---|---|
| Sincronizar | `sigma-sync --what` | `sincronizar_sigma(o_que)` |
| Criar cliente | `sigma-customer-create` | `criar_cliente_sigma` |
| Editar cliente | `sigma-customer-update` | `editar_cliente_sigma` |
| Excluir | `sigma-customer-delete --yes` | `excluir_cliente_sigma(confirmar=True)` |
| Resync | `sigma-customer-resync` | `resync_cliente_sigma` |
| Catálogo servers/packages | `sigma-servers-packages` | `listar_pacotes_sigma` |

Ambos exigem `SIGMA_ALLOW_DESTRUCTIVE=1` para exclusão. Senha mascarada por
padrão nas duas interfaces. Docstrings MCP seguem o formato
**Use quando / Retorna / Cuidados** — o schema dos enums (`o_que`, `status`)
é validado pelo cliente via `Literal`.

### MCP: variáveis de ambiente NÃO são herdadas

Clientes MCP via stdio (Claude Desktop, OpenCode, etc.) **filtram o ambiente
do processo pai** — `SIGMA_PROXY`, `SIGMA_USERNAME` e `SIGMA_PASSWORD` do seu
shell não chegam no servidor. Passe o bloco `env` explícito na configuração,
senão as tools devolvem "Sigma inacessível: sem credenciais":

```json
{
  "automation-hub": {
    "type": "local",
    "command": "venv/bin/python",
    "args": ["main.py", "mcp"],
    "env": {
      "SIGMA_PROXY": "socks5://100.x.y.z:1080",
      "SIGMA_USERNAME": "...",
      "SIGMA_PASSWORD": "..."
    }
  }
}
```

Detalhe: com sessão válida em `sigma_session.json`, as tools funcionam sem
credenciais (só o relogin precisa do par user/password).

## Conhecimento vivo (ordem de leitura para uma IA nova)

1. `AGENTS.md` — hooks do grafo de conhecimento (graphify)
2. `core/automations.py` — o que existe pra fazer
3. `core/sigma/explore/PANEL_MAP.md` — como o painel funciona por dentro
4. `graphify-out/` — grafo do código (`graphify query "..."`)
5. Este README — as regras do jogo

## Deploy (planejado)

VPS + cron para `sigma-sync --what all` diário + alerta de clientes a vencer.
No cron use `timeout --signal=TERM` (SIGKILL deixa Xvfb/Firefox órfãos;
SIGTERM o Playwright trata e faz cleanup).
(dados já no banco; notifier é o que falta). Segundo site real substitui o
placeholder `ecommerce_x` clonando o padrão de pastas do sigma.
