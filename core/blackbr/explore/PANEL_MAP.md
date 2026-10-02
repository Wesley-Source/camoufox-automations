# PANEL_MAP — painelblackbr.com

Fase 1 concluída (exploração read-only com guard — regra do AGENTS.md).
Login: MarcioNPTV (multi-conta via `blackbr_accounts.json` 0600 gitignored).

## Stack

- SPA Vite + Metronic (mesma família UI do sigma.st), rotas `#/...`
- API base: `/api/` no próprio host — **família Sigma** apesar do domínio próprio
- Envelope Laravel: listagens = `{"data": [...], "meta": {...}}`;
  `resellers/list` = array plano `[{id, username, parent}]`
- Falhas conhecidas (idênticas ao woodcine): `/api/settings` 500,
  `/api/statistics/{customers,resellers}` 404

## Auth (core/blackbr/auth.py — genérico, vendor-adaptativo)

- `_login_flow` tenta `input[name=username]` → `email` → `type=text`; se não
  renderizar, tenta tile `button:has-text('{username}')` (estilo v3.94);
  submit `#kt_sign_in_submit` → `button[type=submit]` → Enter; sucesso =
  token no localStorage. Falha dumpa DOM em `explore/out/login_dom.html`.
- `_session_still_valid` PASSIVA (sem fetch a endpoint não garantido):
  URL de login, senha renderizada ou 401 do host ⇒ sessão morta.
- Multi-conta: `blackbr_accounts.json` + `.blackbr_last_good` +
  `BLACKBR_ACCOUNT` env (ordem: env > ponteiro > primeira do arquivo).
- Env própria: `BLACKBR_USERNAME`/`BLACKBR_PASSWORD` (vendor diferente);
  proxy `SIGMA_PROXY` compartilhada (intencional — path da máquina);
  gate destrutivo `SIGMA_ALLOW_DESTRUCTIVE` único entre sites.

## Rotas do painel (23 mapeadas)

Dashboard, feed, integrations (+botbot, reseller-api), notices,
notifications, resellers (+botbot-logs, botbot-scheduled-messages,
bulk-membership, credit-transactions, referral-link, renew-membership,
statistics), server-statistics, support-tickets, active-sessions,
changelog, chatbot, content, system/{credit-packages-price, packages-price},
sign-out.

**É um painel de REVENDAS com CRÉDITOS como moeda** (credit-transactions,
credit-packages-price) — créditos podem ser PAGOS: regra 2 do AGENTS.md em
modo máximo, CRUD proibido sem aprovação.

## API probe (15/18 → 200, sessão reutilizada, zero mutação)

- 200: `auth/me`, `settings/public`, `notices/list`, `resellers/list`,
  `customers?page=1/2`, `customers/expiring`, `customers/statistics`,
  `customers/statistics/top10`, `dashboard/charts/{new-customers,
  customer-retention, revenue-forecast, lost-revenue}`,
  `dashboard/metrics/recovery`, `dashboard/ai-analysis`
- Vistos no load real: `/api/servers` (200 aqui — woodcine dá 403),
  `/api/resellers/customers-count`, `/api/dashboard/preferences`,
  `/api/changelog`, `/api/settings/logo/{id}`
- Schema customers (igual sigma): `{id ~10 chars (pKDNA4ANLX), user_id,
  server_id, package_id, app_server_id, app_package_id, reseller,
  created_at, deleted_at (soft), ...}`; auth/me tem `parent_user_id`

## Fase 2 (pendente aprovação do mapa)

Port do api.py/scraper.py quase direto do woodcine (mesma API), kinds
`blackbr.*` na mesma `panel_entities`; CLI `blackbr-*` + MCP. CRUD por
último e SEM criar entidade real (créditos pagos) — validação só por
probes não-mutantes + tripwire.

## Fase 2 — CRUD portado + ciclo real zz_test ✔ (créditos ilimitados, aprovado pelo dono)

Portado do woodcine (mesma API): `BlackbrApiClient`, kinds `blackbr.*`
(customer/expiring/dashboard_chart/dashboard_metric/reseller/customer_stats/
server/package), CLI `blackbr-*`, 12 tools MCP, gates `SIGMA_ALLOW_DESTRUCTIVE`
+ `--yes`/`confirmar=True`.

**Validação real (ciclo zz_test, 07_test_client_lifecycle.py)** — único site com
 ciclo real liberado (créditos ilimitados):

| Passo | Resultado |
|---|---|
| probe 422 (create sem server/package) | 422 nomeia campos — cria nada ✔ |
| create iterativo | 201, id `RXDgZdBqLe` / `loL7Qm4GWX` ✔ |
| verify-in-list | **casar por ID** (username de 31 chars é truncado pelo painel — match exato falha) ✔ |
| update/renovar | **PROÍBE username/password/password_confirmation** (422 'field is prohibited' — difere do sigma); fix central em `update_customer` faz pop; note aplicada ✔ |
| resync | 200 ✔ |
| delete | 200 soft (`deleted_at`) + gone ✔ |
| tripwire | meta.total estável antes/depois (delta 0) ✔ |

**Churn policy**: painel COMPARTILHADO e vivo (+4–7 clientes no ciclo, e ~5300
rows mudam `m3u_url`/`m3u_url_short` por rotação de domínios de stream:
blackbr.space ↔ blackbr.fun ↔ brblack.site ↔ zro1.site ↔ z1sv.site). Diff
antes/depois é INFORMATIVO para churn de outros revendedores; invariant de
segurança = nosso zz_test sumiu e nada real foi tocado (guard de URL permite
só mutações no ID do teste).

**Perf**: snapshot completo = 103 páginas (~7 min via browser transport);
verify de cliente novo = página 1 (sort `created_at DESC`). Lista completa 2x
só no 07; fluxos rápidos usam `meta.total` + página 1.

**Campos**: `expira`/`expiry_date` veio `None` no row pós-edit — renovação por
`note` aplicada confirmada; mapear campo de expiração real do blackbr antes de
depender de `expiry_date` (provável `due_date`/outro nome).
