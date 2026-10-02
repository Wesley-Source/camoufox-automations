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
