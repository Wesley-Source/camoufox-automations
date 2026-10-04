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

Este projeto manipula **4 painéis de produção com clientes reais** — família
Sigma: lideriptv.sigma.st, woodcine.sigma.st, painelblackbr.com,
newmais.sigma.vin. A segurança não é sugerida — é arquitetural:

1. **Read-only é o padrão.** Escrita só por método nomeado e explícito
   (`create_customer`, `update_customer`...). Não existe método genérico de
   POST/PUT/DELETE na API client — e não crie um.
2. **Guard antes de explorar.** Todo script exploratório instala o guard
   central (`core/guard.py`, via `explore/_guard.py` — wrapper por site) que
   aborta POST/PUT/PATCH/DELETE no nível do browser.
   Mutações intencionais usam o guardião de URL do `07` (allowlist de ID).
3. **Snapshot antes e depois de qualquer escrita.**
   `06_customers_snapshot.py` + diff. Zero divergências além do cliente teste
   é a definição de sucesso.
4. **NUNCA criar/renovar/deletar entidade real sem aprovação EXPLÍCITA do
   dono** — nada de "cliente de teste" por conta própria. Créditos de alguns
   painéis são LIMITADOS/PAGOS (ver tabela abaixo). O único ciclo de teste
   real já aprovado foi no blackbr (créditos ilimitados), sob supervisão.
5. **Destructive pede flag dobrada.** `<site>-customer-delete` exige `--yes`
   no CLI; MCP exige `confirmar=True`. Ambos exigem `SIGMA_ALLOW_DESTRUCTIVE=1`
   no ambiente. Não contorne.
6. **Endpoints em blocklist permanente** (não usar sem aprovação explícita do
   dono): `mass-delete`, `move`, `migration`, BotBot/mensagens, rotas de
   financeiro. O inventário os marca como `blocked`.
7. **PII nunca sai do `out/`.** Snapshots, capturas e sessões ficam em
   diretórios gitignored. Nunca commite token, cookie, senha ou dado de
   cliente.

### Os 4 painéis

| Site | Painel | Créditos | Monitor | Kinds no banco |
|---|---|---|---|---|
| `sigma` | lideriptv.sigma.st | limitados¹ | `/api` | `customer` (legado, sem prefixo) |
| `woodcine` | woodcine.sigma.st | **LIMITADOS** | `/api` | `woodcine.*` |
| `blackbr` | painelblackbr.com | ilimitados | `host` | `blackbr.*` |
| `newmais` | newmais.sigma.vin | **LIMITADOS** | `/api` | `newmais.*` |
| `rocketgestor` | app.rocketgestor.com | inexistentes — zz_test_* **livres**² | n/a (Django) | Fase 2 |

² Rocket Gestor não tem sistema de créditos: criar/alterar/deletar **clientes de
teste** (`zz_test_*`) é livre para validar CRUD — clientes REAIS seguem intocados.

¹ Validação de CRUD **somente por probes não-mutantes** (422 payload inválido,
404 ID inexistente, tripwire de contagem) nos painéis de créditos limitados —
nunca criar entidade real. Regra detalhada: `AGENTS.md` (Painel safety rules).

### Fatos técnicos que vão te poupar horas (já descobertos à moda antiga)

| Fato | Detalhe |
|---|---|
| Transporte | **FAST_SYNC ativo ×4** (validado 03/10/2026): syncs usam HTTP direto via `curl_cffi` (impersonate Chrome + cookies/token da sessão + DoH) — 3-5x mais rápido que browser, com fallback automático pro browser em 403/challenge (que refresha `cf_clearance`). Detalhe: Cloudflare bloqueia `requests` puro (fingerprint TLS); dentro do browser, `fetch` via `page.evaluate` usa o DoH + TLS real do Firefox. |
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
  guard.py              # GUARD CENTRAL — kill switch de mutação (wrapper por site: core/<site>/explore/_guard.py)
  panel_auth.py         # BASE compartilhada: sessão multi-conta, ensure_logged_page, monitor
  panel_api.py          # BASE compartilhada: PanelApiClient (GET whitelist + mutações nomeadas) + _HttpTransport (curl_cffi, FAST_SYNC) + _BrowserTransport
  panel_scraper.py      # BASE compartilhada: sync_* genérico (kinds prefixados por site)
  sigma/                # SITE: lideriptv.sigma.st (estrutura idêntica nos 4)
    auth.py             #   config + _login_flow + wrappers (paridade testada em CI)
    api.py              #   <Site>ApiClient (subclasse de PanelApiClient)
    scraper.py          #   sync_* (ELT: fetch → raw → panel_entities, kinds prefixados)
    explore/            #   scripts de descoberta (dev, mantêm o mapa vivo)
      _guard.py         #     wrapper do guard central
      01..07_*.py       #     sessão, mapa, crawl, probe, crudmap, snapshot, lifecycle
      PANEL_MAP.md      #     MAPA CANÔNICO do painel (endpoints, schema, descobertas)
      out/              #     capturas (GITIGNORED — PII)
  woodcine/             # SITE: woodcine.sigma.st (idêntico ao sigma/)
  blackbr/              # SITE: painelblackbr.com (idêntico ao sigma/)
  newmais/              # SITE: newmais.sigma.vin (idêntico ao sigma/)
  ecommerce_x/          # SITE: placeholder httpbin (padrão para o próximo site)
    scraper.py
    explore/
interfaces/
  cli/                  # Typer: __init__ (hub+automations) + um módulo por site
  mcp/                  # FastMCP: server.py (hub) + um módulo por site (50 tools)
tests/                  # pytest (151 testes; paridade ×4 em CI — drift entre sites quebra o build)
main.py                 # `main.py` = CLI | `main.py mcp` = servidor MCP
```

### Arquivos por site (padrão `<site>_*`, todos gitignored na raiz)

- `<site>_session.json` — sessão primária (token + cookies)
- `.<site>_session_<usuario>.json` — sessão por conta extra (multi-conta)
- `<site>_accounts.json` — credenciais (0600; mesma ordem = prioridade)
- `.<site>_last_good` — ponteiro da conta ativa

Sessão válida = `GET /api/auth/me` 200. newmais é Bearer-only (cookies
vazios são válidos). `monitor_scope` do explorador: `/api` (padrão) ou
`host` (blackbr — vendor desconhecido na época).

## Setup

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/camoufox fetch                  # baixa o browser (~1x)
pytest tests/                            # deve passar 151/151
# credenciais por painel: <site>_accounts.json (ou env SIGMA_USERNAME/SIGMA_PASSWORD):
venv/bin/python main.py newmais-account add Techcarlos2   # exemplo (senha oculta, 0600)
venv/bin/python main.py newmais-login --save               # gera newmais_session.json (gitignored)
```

## Windows & displays

O browser de evasão (Camoufox) usa **Xvfb (display virtual)**, que só existe
no Linux. No Windows você tem 3 caminhos, do melhor pro pior:

### 1) WSL2 (recomendado — experiência idêntica ao Linux)

```powershell
wsl --install -d Ubuntu        # PowerShell como admin, reinicia
```

Dentro do Ubuntu (tudo inclusive o browser funciona — Xvfb incluso):

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone <seu-repo> && cd camoufox-automations
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/camoufox fetch
venv/bin/python main.py newmais-login --save    # login browser normal
```

Aponte o cliente MCP (ex.: Hermes desktop) para o hub rodando dentro do WSL.

### 2) Windows nativo com `HUB_DISPLAY=headless`

Browser nativo sem janela. **Revalide o Cloudflare painel a painel** — a
impressão digital do headless nativo difere do virtual e o CF pode reagir
diferente:

```powershell
$env:HUB_DISPLAY = "headless"
venv\Scripts\python main.py woodcine-status     # teste painel a painel
```

### 3) Windows nativo com X server externo (`HUB_DISPLAY=x11`)

Instale o VcXsrv, exporte `DISPLAY=<ip>:0` e use `HUB_DISPLAY=x11`.

### O que funciona no Windows SEM browser nenhum

O transporte HTTP (FAST_SYNC, curl_cffi) e tudo que lê o banco local não
abrem browser — no Windows nativo funcionam de primeira:

```powershell
venv\Scripts\python main.py blackbr-sync --what expiring   # HTTP puro, ~2s
venv\Scripts\python main.py automations                     # inventário
# busca local: buscar_cliente_* / listar_clientes_* via MCP
```

O que **precisa** de browser: login fresco, validação de expiração,
exploradores. Sem display configurado, esses comandos falham com mensagem
orientada apontando para as opções acima.


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
2. **Ler o mapa antes de tocar** → `core/<site>/explore/PANEL_MAP.md` tem
   endpoints, schemas e pegadinhas por seção do painel (4 mapas, um por site).
3. **Sincronizar dados** → `<site>-sync --what all` (banco local sempre;
   UPSERT idempotente; FAST_SYNC torna isso barato — rotina diária:
   `--what expiring`).
4. **Criar/editar/excluir cliente** → comandos `<site>-customer-*` / tools MCP.
   ⚠️ Só com aprovação EXPLícita do dono (painéis de créditos limitados:
   NUNCA; validação só por probes não-mutantes). Antes: snapshot (06).
   Depois: snapshot + diff = zero.
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
| `ok` | 60+ | login/sync/status/CRUD por painel (×4), 7+ exploradores por site, demo ecommerce |
| `planned` | ~8 | notices, top10, ai-analysis, export CSV, restore, sync agendado |
| `blocked` | 3+ | BotBot/mensagens, bulk (mass-delete/move/migration), financeiro |

## Interfaces

**CLI** (`venv/bin/python main.py <comando>`): um módulo por site registra
comandos `<site>-login`, `<site>-account list|use|add|remove`, `<site>-sync`,
`<site>-status`, `<site>-servers-packages`, `<site>-customer-create|update|delete|resync`
(sigma, woodcine, blackbr, newmais) + `automations`, `sync-item`.
MCP (`main.py mcp`): **50 tools** — 12-14 por painel (login, sincronizar,
status, contas ×2, pacotes, buscar/listar clientes + CRUD ×4 com gates) +
`listar_automacoes` + ecommerce. A fonte viva é `main.py automations`.

### Paridade CLI ↔ MCP

| Ação | CLI | MCP |
|---|---|---|
| Sincronizar | `<site>-sync --what` | `sincronizar_<site>(o_que)` |
| Criar cliente | `<site>-customer-create` | `criar_cliente_<site>` |
| Editar cliente | `<site>-customer-update` | `editar_cliente_<site>` |
| Excluir | `<site>-customer-delete --yes` | `excluir_cliente_<site>(confirmar=True)` |
| Resync | `<site>-customer-resync` | `resync_cliente_<site>` |
| Catálogo servers/packages | `<site>-servers-packages` | `listar_pacotes_<site>` |

(site = sigma, woodcine, blackbr ou newmais — mesma forma em todos os 4.)

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

1. `AGENTS.md` — regras de segurança + hooks do grafo de conhecimento (graphify)
2. `core/automations.py` — o que existe pra fazer (fonte viva)
3. `core/<site>/explore/PANEL_MAP.md` — como cada painel funciona por dentro (4 mapas)
4. `graphify-out/` — grafo do código (`graphify query "..."`)
5. Este README — as regras do jogo

## Deploy (planejado)

VPS + cron para `<site>-sync --what expiring` diário (~2s/painel via
FAST_SYNC) + sync completo semanal + alerta de clientes a vencer.
No cron use `timeout --signal=TERM` (SIGKILL deixa Xvfb/Firefox órfãos;
SIGTERM o Playwright trata e faz cleanup).
