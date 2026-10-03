# PANEL_MAP — newmais (painelblackbr era o 3º; este é o 4º painel do hub)

Stack: família SIGMA confirmada — mesma base `/api/`, envelope Laravel
`{"data": [...]}`, mesmo padrão de falhas do woodcine/blackbr:
`/api/settings` 500 e `/api/statistics/{customers,resellers}` 404 (15/18 → 200).

## Auth (peculiaridade deste painel)

- **Bearer puro**: o login NÃO seta cookies — só token no localStorage.
  `load_session` da base (`core/panel_auth.py`) foi ajustado para aceitar
  sessão com token e cookies vazios (cookies são suplementares).
- Login clássico: `input[name=username]` + `#kt_sign_in_submit` (sem tile
  v3.94 do woodcine). `_LOGIN_FORM_TIMEOUT=30_000` (CF ~10s, Hermes G2).
- Multi-conta: `newmais_accounts.json` (0600 gitignored) + `.newmais_last_good`.
- Conta ativa: Techcarlos2 (créditos LIMITADOS — regra 2 do AGENTS.md em
  modo máximo: NUNCA criar/renovar/deletar entidade real; CRUD só por
  probes não-mutantes 422/404/tripwire).

## Rotas (02_dashboard_map + 03_route_crawl)

#/dashboard, #/feed, #/integrations (+/botbot, /reseller-api), #/notices,
#/notifications, #/resellers (+/botbot-logs, /botbot-scheduled-messages,
/bulk-membership, /credit-transactions, /referral-link, /renew-membership,
/statistics), #/server-statistics, #/sign-out, #/support-tickets,
#/system/credit-packages-price, #/system/packages-price,
#/active-sessions, #/changelog, #/chatbot, #/content

Menu confirma painel de REVENDAS com CRÉDITOS: "Comprar Créditos",
"Assistente de Renovação (Beta)", "Conexões Ao Vivo".

## API (04_api_probe — 15/18 → 200)

- 200: `/api/auth/me`, `/api/settings/public`, `/api/notices/list`,
  `/api/resellers/list`, `/api/customers?page=1|2`,
  `/api/customers/expiring`, `/api/customers/statistics` (+top10),
  `/api/dashboard/charts/{new-customers,customer-retention,revenue-forecast,lost-revenue}`,
  `/api/dashboard/metrics/recovery`, `/api/dashboard/ai-analysis`
- Falhas conhecidas (iguais nos irmãos): `/api/settings` 500,
  `/api/statistics/customers` 404, `/api/statistics/resellers` 404
- Monitor do explorador em modo `host` (config do site) — sem suposição
  de prefixo de API.

## Fase 2 — CRUD portado + probes não-mutantes ✔

Portado do woodcine (template família Sigma) sobre as bases compartilhadas:
`api.py` = subclasse de `PanelApiClient` (~70 linhas, sem strip — se update
um dia 422, aplicar fix como no blackbr); `scraper.py` kinds `newmais.*`;
CLI `newmais-*` + 12 tools MCP; paridade ×4 em CI.

**Gates destrutivos**: `SIGMA_ALLOW_DESTRUCTIVE=1` + `--yes` (CLI) /
`confirmar=True` (MCP). Saídas projetam `project_customer`/`project_response`.

**Validação sem mutação** (créditos LIMITADOS — regra 2 máxima, NUNCA
entidade real; diferença do blackbr, que tinha créditos ilimitados):
- probe 422: POST /customers payload inválido (`username: '!!!'`) → Laravel
  nomeou os campos, criou NADA
- probe 404: PUT/DELETE /customers/zz_probe_fake → 404
- tripwire: meta.total=195 antes/meio/depois — idêntico, painel intocado ✔
