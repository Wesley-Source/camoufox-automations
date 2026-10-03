# PANEL MAP — woodcine.sigma.st (mapeado em 01/10/2025)

Mapeamento não-destrutivo (guard read-only em 100% das execuções, zero mutação).
Método: playbook 01→04 (sessão → mapa passivo → crawl com blocklist → probe GET).
Creds: `woodcine_accounts.json` (gitignored). Sessão: `woodcine_session.json`.

## Auth (idêntico ao lider)

- `POST /api/auth/login` `{username, password}` → token Laravel `id|hash` em `localStorage["token"]`
- `Authorization: Bearer <token>`; Cloudflare `cf_clearance` (IP-bound — SIGMA_PROXY único)
- Validação: `GET /api/auth/me` (200 = válida)
- **Mutações exigem headers axios** `Accept: application/json` + `X-Requested-With: XMLHttpRequest` (sem eles: 302→HTML status 200 falso-sucesso)
- Creds: login `Marcioadmelite` (senha em `woodcine_accounts.json`, 0600 — NUNCA em doc; `Il` = i+L, NÃO `ll` — 1 tentativa errada gasta contador de ban, ~9 = ban permanente)

## UI — 84 rotas mapeadas (vs 42 do lider)

Painel mais novo que o lider. Rotas extras que o lider não tem:
`#/feed`, `#/integrations` (+`/botbot`, `/reseller-api`), `#/support-tickets`,
`#/resellers/botbot-scheduled-messages`, `#/resellers/credit-transactions`,
`#/customers/renewal-assistant` (beta), `#/customers/migration`.

10 rotas seguras crawleadas (out/routes/*.json + .png): account-security¹,
active-sessions, changelog, content, customers, customers/live-connections,
customers/statistics (1 tabela), dashboard, feed (11 GETs), notifications,
server-statistics.
¹ Não dispara nenhum GET no load (descartada 2x) — provavelmente exige interação.

Blocklist permanente (73 rotas puladas): settings/config, users/admin,
billing/invoice/finance/payment, edit/add/create/delete forms, credit/purchase/
migrate/renew, botbot/message/reminder/ticket, sign-out.

## API — probe 15/18 (out/api/*.json)

| Endpoint | Status | Nota |
|---|---|---|
| GET /api/auth/me | 200 | profile + membership_expiry_date |
| GET /api/settings/public | 200 | |
| GET /api/notices/list | 200 | |
| GET /api/resellers/list | 200 | |
| GET /api/customers?page=N | 200 | `perPage` camelCase, cap 100 |
| GET /api/customers/expiring | 200 | |
| GET /api/customers/statistics | 200 | |
| GET /api/customers/statistics/top10?from_date&to_date | 200 | datas ISO Z |
| GET /api/dashboard/charts/{new-customers,customer-retention,revenue-forecast,lost-revenue} | 200 | |
| GET /api/dashboard/metrics/recovery | 200 | |
| GET /api/dashboard/ai-analysis | 200 | |
| GET /api/settings | **500** | igual ao lider v3.93 — quebrado no painel |
| GET /api/statistics/{customers,resellers} | **404** | paths antigos; use os de cima |
| GET /api/servers/{id} | **403** | (report de exploração externa) |
| GET /api/packages | **403** | use /packages/list |

Confirmados por outra sessão: GET /api/servers (200) e /api/packages/list (200,
com server_id). Envelope Laravel `{"data": [...]}` em /servers e /packages/list
— sync precisa do unwrap (feita no lider em 47e3f25).

## Clientes

- Lista = cards com botões de ação (sem `<table>`); UI não dispara
  `GET /api/customers` no load (busca direta na API)
- IDs ~10 chars (`KjLM54xL04`); edit em `#/customers/edit/{id}`
- Delete = soft (deleted_at); restore via `POST /customers/restore`
- `resync` (`POST /customers/{id}/resync`) retorna a linha COMPLETA — projetar
  campos públicos antes de exibir (nunca password/m3u_url/renew_url)

## Fase 2 — CRUD portado + probes não-mutantes ✔

Portado do sigma com kinds prefixados `woodcine.*` na mesma `panel_entities`
(customer/expiring/dashboard_chart/dashboard_metric/reseller/customer_stats/
server/package). `WoodcineApiClient` + CLI `woodcine-*` + 12 tools MCP.

**Login v3.94** (diferente do lider v3.93): com conta recente o painel mostra
tela de confirmação (botão `{username} Último uso`) em vez do form clássico —
`_login_flow` clica no botão da conta, depois preenche `input[name=password]`
(submit via `#kt_sign_in_submit` ou Enter). Sucesso = polling direto de
`localStorage.token` por 90s — única fonte da verdade (a navegação
pós-login destrói o contexto JS; monitor nem sempre captura o POST).
Fix 8ac91f9.

**Gates destrutivos**: `SIGMA_ALLOW_DESTRUCTIVE=1` + `--yes` (CLI) /
`confirmar=True` (MCP). Resync/editar projetam `project_customer` (nunca
password/m3u_url/renew_url).

**Validação sem mutação** (créditos limitados — nunca criar entidade real):
- probe 422: POST /customers com payload inválido (`username: '!!!'`) →
  Laravel valida antes de criar; retorna 422 nomeando campos, cria NADA
- probe 404: PUT/DELETE /customers/zz_probe_fake → 404, ninguém tocado
- tripwire: snapshot de clientes (meta.total=7876) antes/depois de cada
  probe — idêntico, zero divergência; espelho local 2500 clientes em
  `woodcine.customer`

