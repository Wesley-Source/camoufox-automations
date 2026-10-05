# Camoufox Automations

**Production-grade stealth browser-automation hub — for humans and AI agents.**

Multi-panel web automation built to be operated by AI agents (Hermes, OpenCode, any MCP client) and humans alike. Stealth browser (Camoufox), ELT into SQLite, Typer CLI + FastMCP server — one folder per automated site, shared engines, security enforced by architecture.

[![Tests](https://img.shields.io/badge/tests-6%20passing%20%2B%20157%20in%20panels%20repo-brightgreen)]() [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.10%2B-blue)]() [![MCP](https://img.shields.io/badge/MCP-compatible-purple)]()

> **Are you an AI agent reading this?** Start with the [Golden Rules](#golden-rules-for-ai) and the [automation inventory](#automation-inventory). They summarize what you can do, how, and what you must **never** do.

## Why this exists

Automating authenticated admin panels safely is an unsolved gap between raw browser frameworks (Playwright) and free-roaming agents (browser-use): real panels have paying data, anti-bot walls, and no API docs. This hub fills it with an opinionated architecture:

- **Read-only by default** — writes only through explicitly named methods; no generic POST/PUT/DELETE exists in the API client, by design
- **Central mutation guard** — exploratory scripts install a kill switch that aborts mutating HTTP at the browser level
- **Snapshot → write → snapshot + diff** — zero divergence beyond the test entity is the definition of success
- **Double destructive gates** — `--yes` flag *and* an environment flag; neither alone is enough
- **CLI ⇄ MCP parity enforced in CI** — a fix in one interface must land in the other; a drift test fails the build

## Golden Rules for AI

Security here is not suggested — it is architectural:

1. **Read-only is the default.** Writes only via named explicit methods. There is no generic mutation method in the API client — don't create one.
2. **Guard before exploring.** Every exploratory script installs the central guard (`core/guard.py`) which aborts POST/PUT/PATCH/DELETE at the browser level.
3. **Snapshot before and after any write.** `snapshot.py` + diff. Zero divergence beyond the test entity = success.
4. **NEVER create/renew/delete a real entity without the owner's EXPLICIT approval.** CRUD validation on production panels is probe-only (invalid-payload 422, nonexistent-ID 404, count tripwire).
5. **Destructive requires double flags.** CLI demands `--yes`; MCP demands `confirmar=True`; both demand `SIGMA_ALLOW_DESTRUCTIVE=1` in the environment. Don't bypass.
6. **PII never leaves gitignored directories.** Never commit tokens, cookies, passwords, or customer data.
7. **Panel targets are private config.** This repo ships with an `ecommerce_x` example site. Real site modules live in the private companion repo (`camoufox-panels`) — panel URLs/names never enter this repo.

## Architecture (one folder per site)

```
core/
  automations.py        # INVENTORY — single source of truth (CLI/MCP/README read from here)
  browser.py            # Camoufox headless (virtual display) + Google DoH
  database.py           # SQLite: raw_snapshots, panel_entities (UPSERT)
  guard.py              # CENTRAL GUARD — mutation kill switch
  panel_auth.py         # shared base: multi-account sessions, ensure_logged_page
  panel_api.py          # shared base: PanelApiClient (GET whitelist + named mutations)
                        #   + _HttpTransport (curl_cffi, FAST_SYNC) + _BrowserTransport
  panel_scraper.py      # shared base: generic sync_* (prefixed kinds per site)
  ecommerce_x/          # example site (httpbin-based) — template for the next one
  <site>/               # per-site: auth, api, scraper, explore/ (read-only probes)
    auth.py             #   config + _login_flow + wrappers (parity tested in CI)
    api.py              #   <Site>ApiClient (subclasses PanelApiClient)
    scraper.py          #   sync_* (ELT: fetch → raw → panel_entities)
    explore/            #   discovery scripts (dev-time; keep the map alive)
      PANEL_MAP.md      #     canonical endpoint/schema map per panel
                        #   ↑ real sites live in the PRIVATE companion repo
interfaces/
  cli/                  # Typer: _panel.py ENGINE (10 commands) + ~30-line spec per site
  mcp/                  # FastMCP: _panel.py ENGINE (12 tools) + ~45-line spec per site
tests/                  # pytest — framework tests; per-site tests live in the private repo
main.py                 # `main.py` = CLI | `main.py mcp` = MCP server
```

### Adding a new site = ~75 lines of spec

Copy the engine spec, fill the `SiteConfig` (URL, auth type, monitor scope), and you get the full surface: login, multi-account, sync, status, catalog, search, CRUD with gates — on both CLI and MCP, tested in CI. See `CONTRIBUTING.md`. Real client panels go in the **private** companion repo; `ecommerce_x` here is the worked example.

## Quick start

```bash
git clone https://github.com/Wesley-Source/camoufox-automations.git
cd camoufox-automations
python3 -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/camoufox fetch                     # downloads the stealth browser (once)
venv/bin/python -m pytest tests/ -q         # 6 framework tests passing
venv/bin/python main.py automations         # live inventory of what exists
```

Connect a panel: `python main.py <site>-account add NAME` (password prompted, stored 0600, gitignored). Or point an MCP client at `main.py mcp`.

## Connecting real panels (private companion repo)

Real site modules are **not** in this repo — they live in the private `camoufox-panels` repo (panel URLs, PANEL_MAPs, per-site tests). The framework runs standalone; sites attach via **local symlinks**:

```bash
# both repos side by side:
projetos/camoufox-automations/    # this repo (public framework)
projetos/camoufox-panels/         # private sites repo

cd ../camoufox-panels && ./join.sh    # idempotent; ./join.sh --unlink reverts
```

`join.sh` symlinks each site module back into its original path here (`core/<site>/`, `interfaces/{cli,mcp}/<site>.py`, `mcp/playlist.py`) and symlinks the shared engines into the private repo so its tests run standalone. With the join, the full surface returns (all `<site>-*` commands, 50+ MCP tools, 163 total tests); without it, this repo still runs and `--help` shows a notice about missing site modules.

## Performance highlights (measured, not hoped)

| Optimization | Effect |
|---|---|
| FAST_SYNC — direct HTTP via `curl_cffi` (Chrome TLS fingerprint + session cookies + DoH), browser fallback on 403/challenge | 3–5× faster syncs; validated in production ×4 |
| Server-side search before pagination | 10k-customer search: full cycle −33% (43.3s → 29.2s) |
| TLS keep-alive (single curl_cffi Session) | CF handshake once per process; −10% full cycle |
| In-memory DoH cache (TTL 300s) | Sub-100ms resolution; disk cache tested and rejected |
| Lazy `core.browser` imports (PEP 562) | Test cycle 1.21s → 0.53s; offline commands never pay the browser import |

## Multi-account

Credentials in `<site>_accounts.json` (gitignored, 0600); file order = priority. Active account resolved per command: `SIGMA_ACCOUNT` env > `. <site>_last_good` pointer > first in file. Each account keeps its own session file. CLI: `<site>-account list|use|add|remove`; MCP: `listar_contas_*` / `trocar_conta_*`.

## Windows

The stealth browser needs a virtual display (Linux/Xvfb). On Windows: WSL2 (recommended, everything works), native headless (`HUB_DISPLAY=headless` — revalidate anti-bot per panel), or an external X server (`HUB_DISPLAY=x11`). Everything HTTP-only (FAST_SYNC, local DB reads) works on native Windows with no display at all.

## How an AI agent operates this

1. **Discover** → `main.py automations` (or MCP `listar_automacoes`). `ok` = usable; `planned` = mapped, not wired; `blocked` = explicit human approval required.
2. **Read the map** → `core/<site>/explore/PANEL_MAP.md` in the private repo (endpoints, schemas, gotchas per panel section).
3. **Sync data** → `<site>-sync --what all` (daily routine: `--what expiring`, ~2s via FAST_SYNC).
4. **CRUD** → `<site>-customer-*` commands / MCP tools — only with explicit owner approval, snapshot before, snapshot+diff after.
5. **Explore new areas** → guard on, sensitive-section blocklist, small `--max`, one commit per script, findings into PANEL_MAP.md.
6. **Add an automation** → core in `core/<site>/`, command in `interfaces/cli/`, tool in `interfaces/mcp/`, test in `tests/`, one line in `core/automations.py`.

## Interfaces

**CLI** (`main.py <command>`): `automations`, `sync-item` (framework, always) + per-site `<site>-login`, `<site>-account list|use|add|remove`, `<site>-sync`, `<site>-status`, `<site>-servers-packages`, `<site>-customer-create|update|delete|resync` (with the private repo joined).

**MCP** (`main.py mcp`): inventory + example-site tools always; with the join, **50+ tools** — 12–14 per panel (login, sync, status, accounts ×2, catalog, search/list + gated CRUD ×4). Docstrings follow the **Use when / Returns / Cautions** format; enum schemas validated via `Literal`.

MCP-over-stdio clients filter the parent environment — pass `env` explicitly in the client config (documented below in the original README; see `AGENTS.md`).

## Community

- [CONTRIBUTING.md](CONTRIBUTING.md) — ground rules, dev setup, PR process (AI-agent contributors welcome; read `AGENTS.md` first)
- [License: MIT](LICENSE)
- Bug reports: redact all credentials, tokens, and panel URLs

## Knowledge map (reading order for a fresh AI)

1. `AGENTS.md` — safety rules + knowledge-graph hooks
2. `core/automations.py` — what exists to be done (living source)
3. `core/<site>/explore/PANEL_MAP.md` (private repo) — how each panel works inside
4. This README — the rules of the game
