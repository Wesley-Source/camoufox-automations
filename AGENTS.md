## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Painel safety rules (REGRA PERMANENTE — humanos e agentes de IA)

Este hub opera painéis de clientes REAIS (lideriptv, woodcine, painelblackbr, ...).
Créditos e clientes nesses painéis PODEM SER LIMITADOS/PAGOS. Regras inegociáveis:

1. **Exploração é read-only.** Todo script em `core/*/explore/` roda somente-leitura
   e DEVE instalar o guard: `ensure_logged_page(..., guard=install_guard)` de
   `core/guard.py`. Script de exploração sem guard é bug. O log deve terminar com
   `✔ Guard: nenhuma request mutante tentada`.
2. **Nunca criar/renovar/deletar entidade real** (cliente, revendedor, pacote) sem
   aprovação EXPLÍCITA do dono. Nada de "cliente de teste" por conta própria.
3. **Validação de CRUD só por probes não-mutantes**: 422 (POST com payload
   deliberadamente inválido → o backend valida antes de criar, cria NADA), 404
   (PUT/DELETE em ID inexistente), tripwire (contagem/listagem de clientes antes
   e depois de cada probe — divergiu, parou). Sempre com snapshot antes/depois.
4. **Gates destrutivos em dobro**: mutação destrutiva exige flag de ambiente
   `SIGMA_ALLOW_DESTRUCTIVE=1` (humano seta) E confirmação explícita (`--yes` no
   CLI / `confirmar=True` no MCP). Confirmação preenchida pelo próprio agente
   não vale.
5. **Nunca vazar segredos**: saídas usam `project_*` (jamais password, m3u_url,
   renew_url, token completo).
6. **Login sem brute-force**: tentativa errada em `/login` pode contar para ban
   permanente. Só tenta com credencial confirmada; sessão salva é reutilizada
   (os exploradores já fazem isso via `ensure_logged_page`).
7. **Site novo** = seguir o padrão `core/<site>/` (auth multi-conta com
   `<site>_accounts.json` 0600 gitignored, `explore/` com guard, `PANEL_MAP.md`,
   kinds prefixados `<site>.*` no banco). Explorar primeiro, mapear, SÓ DEPOIS
   portar api/scraper/CLI/MCP — e CRUD por último.

## Operational guidelines (browser/CF) — post-mortem Hermes 02/10/2026

1. **Proxy no boot do browser**: `BrowserEngine.get_page` já aplica o fallback
   da env `SIGMA_PROXY` internamente — nunca abra browser sem proxy em painel
   atrás de Cloudflare (egress da máquina = CF bloqueia).
2. **Primeiro `wait_for_selector` pós-goto ≥20s** e sempre via constante
   nomeada `_LOGIN_FORM_TIMEOUT` em cada `core/*/auth.py` (CF pode levar ~10s;
   timeouts curtos dão falha intermitente que parece "form não encontrado").
3. **Validação de sessão sempre com cheque ativo** (fetch GET read-only tipo
   `/api/auth/me` com Bearer) além dos sinais passivos — página de challenge
   do CF passa na checagem passiva e daria falso positivo "sessão válida".
4. **CF = esperar, não falhar**: `_login_flow` e validação usam
   `core.browser.is_cf_challenge(page)` (title 'Just a moment'/'Attention
   Required' ou elementos de challenge) e aguardam em loop antes de concluir
   que o form não existe.
5. **PARIDADE entre auth.py's**: correção num painel replica nos outros NA
   MESMA rodada (os 3 são gêmeos). As bases compartilhadas são `core/panel_auth.py`, `core/panel_api.py` e
   `core/panel_scraper.py` — correção vai no BASE, não nas cópias; `core/<site>/{auth,api,scraper}.py` é só
   config + `_login_flow` + wrappers. Painel novo = copiar o auth.py mais
   completo e conferir item a item. `tests/test_auth_parity.py` falha se a
   superfície pública divergir.
6. **NÃO fazer**: múltiplos browsers/logins simultâneos (red flag CF), raspar
   DOM quando existe API JSON, repetir requests sem rate limit.
7. **Sync rápido**: os clients usam transporte HTTP direto (curl_cffi) com
   fallback automático pro browser (`FAST_SYNC` validado ×4 em 03/10/2026).
   Rotina diária: `--what expiring` (1 request ~2s); sync completo só no boot
   ou semanal. Exploradores continuam SEMPRE browser + guard.
