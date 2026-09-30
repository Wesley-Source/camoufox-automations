# Mapa do painel LIDER SERVERS (lideriptv.sigma.st) — v3.93

Gerado pelos explorers em `core/sigma/explore/` (tudo GET/read-only; guard
aborta POST/PUT/PATCH/DELETE no nível do browser). Capturas brutas (com PII)
ficam em `out/` — gitignored. Referência manual prévia: endpoints testados
com GET+Bearer salvos em cache/scratch/panel_data/all/.

## Auth (o fluxo inteiro)

1. **Login só via navegador** (Cloudflare na frente): `POST /api/auth/login`
   `{username, password}` a partir do form (`input[name=username]`,
   `input[name=password]`, `button#kt_sign_in_submit`).
2. **Token** vai para `localStorage["token"]` (formato Laravel `id|hash`,
   SEM expiração decodificável no cliente) e depois via
   `Authorization: Bearer <token>`.
3. `cf_clearance` (cookie .sigma.st) sozinho NÃO dá acesso à API.
4. **Validação de sessão**: `GET /api/auth/me` → 200 = válido, 401 = expirado.
   Sem credenciais locais de expiração — quem decide é o servidor.
5. Sessão canônica: `sigma_session.json` (token + cookies + localStorage),
   reutilizada por `ensure_logged_page()`; `01_session.py` refresca.

## Endpoints da API verificados (200, GET + Bearer)

### Auth / settings
| Endpoint | Uso |
|---|---|
| `GET /api/auth/me` | perfil completo + config BotBot + membership (`membership_expiry_date`, templates, `membership_plan_type`) |
| `GET /api/settings/public` | settings públicas (logo, tema) |
| `GET /api/settings/logo/{id}` | logo do painel |

### Clientes
| Endpoint | Uso |
|---|---|
| `GET /api/customers?page=N` | lista paginada (p1 e p2 confirmados; prova manual p1–p9) |
| `GET /api/customers/expiring` | clientes a vencer |
| `GET /api/customers/statistics` | estatísticas |
| `GET /api/customers/statistics/top10?from_date=...&to_date=...` | top 10 (janela vista no dashboard) |
| `GET /api/customers/live-connections` | usado pela rota Conexões Ao Vivo |

### Revendas
| Endpoint | Uso |
|---|---|
| `GET /api/resellers/list` | lista de revendas |

### Dashboard / gráficos
| Endpoint | Uso |
|---|---|
| `GET /api/dashboard/charts/new-customers` | gráfico novos clientes |
| `GET /api/dashboard/charts/customer-retention` | retenção |
| `GET /api/dashboard/charts/revenue-forecast` | previsão de receita |
| `GET /api/dashboard/charts/lost-revenue` | receita perdida |
| `GET /api/dashboard/metrics/recovery` | métricas de recuperação |
| `GET /api/dashboard/ai-analysis` | análise IA |
| `GET /api/notices/list` | avisos |

### Falhas registradas (não insistir sem revisar)
- `GET /api/settings` → **500** (o `panel_expiration_date` citado na coleta
  manual morava aqui; nesta v3.93 o GET direto quebra — expiração do painel
  hoje visível só na UI; `auth/me.membership_expiry_date` cobre a conta).
- `GET /api/statistics/customers|resellers` → **404** (paths da coleta manual;
  a v3.93 usa `/api/customers/statistics` e `/api/resellers/list`).

## Rotas da UI (#/, 42 mapeadas pelo 02)

Crawleo read-only (03): 10 liberadas e capturadas em `out/routes/`
(account-security, active-sessions, changelog, content, customers,
customers/live-connections, customers/statistics, dashboard, notifications,
server-statistics). 32 na blocklist conservadora: settings/config, billing,
creditos/compra, forms `add|edit`, renovação/migração, BotBot/mensagens,
tickets, resellers, sign-out (mataria a sessão), usuários/admin.

Observação: a lista de clientes na UI NÃO dispara `GET /api/customers` no
load — os cards carregam sob demanda (scroll/busca). Para dados, use a API
direta (`04_api_probe.py`), não a UI.

## Descobertas de UI (para scrapers futuros)

- Lista de clientes = cards com botões de ação (Renovar, Adicionar Créditos,
  Detalhes do Cliente, Nova Mensagem) — sem `<table>`; editar cliente tem
  rotas `#/customers/edit/{id}` (IDs curtos tipo `2YD0JXlv1Q`).
- Dashboard = cards + gráficos, dados vêm dos endpoints `/api/dashboard/*`.
- Sidebar completa no screenshot `out/dashboard.png`.

## Segurança da exploração

- `_guard.py`: kill switch de rede (só GET/HEAD/OPTIONS passam); instalado
  após o login. Em TODAS as etapas o guard registrou **zero** tentativas
  mutantes — nenhuma escrita aconteceu.
- 03: navegação só por `location.hash` (equivale a GET), espera
  determinística de router (hash+título), parada por anomalia
  (sign-in/5xx/Cloudflare), `--max N` por execução, resumível.
- Sessão/PII em `out/` e `sigma_session.json` — gitignored.
