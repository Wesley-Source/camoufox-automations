# Contributing to Camoufox Automations

First off, thank you for considering contributing! This project is operated by both humans and AI agents, and contributions from both are welcome.

## Project overview

Camoufox Automations is a stealth browser-automation hub: one folder per automated site, shared engines for CLI (Typer) and MCP (FastMCP) interfaces, ELT into SQLite, and a test suite that gates every change.

```
core/ecommerce_x/     # example site (httpbin) — the worked template
core/panel_*.py       # shared base classes (SiteConfig, auth, api, scraper)
interfaces/cli/       # Typer CLI engines + registry (site specs come from the private repo)
interfaces/mcp/       # FastMCP engines + registry (site specs come from the private repo)
tests/                # framework tests; per-site tests live in camoufox-panels (private)
```

Real site modules live in the **private** companion repo `camoufox-panels`; clone it side by side and run `../camoufox-panels/join.sh` to attach it (see README "Connecting real panels").

## Ground rules

1. **Read-only by default.** Any new write path must be an explicitly named method (`create_customer`, `update_customer`). No generic POST/PUT/DELETE helpers.
2. **Guard before exploring.** Exploratory scripts must install the central guard (`core/guard.py`) that blocks mutating HTTP at the browser level.
3. **Snapshot before and after writes.** Divergence beyond the test entity = failure.
4. **No secrets, ever.** Credentials live in `*_accounts.json` / `*_session.json` (gitignored, 0600). If you find a secret anywhere, report it privately — do not open a public issue.
5. **Parity is enforced.** A fix in one site's `auth.py` must be replicated in the shared base (`core/panel_auth.py`) or all sibling sites. `tests/test_auth_parity.py` (private repo) fails on public-surface drift.
6. **Docs travel with code.** A behavior change without a README/AGENTS.md/docstring update in the same commit is an incomplete commit.
7. **Lazy imports for heavy modules.** `core.browser` (Playwright/Camoufox, ~0.5s) must not be imported at module top-level in `auth.py` files — use PEP 562 `__getattr__`.

## Dev setup

```bash
git clone https://github.com/Wesley-Source/camoufox-automations.git
cd camoufox-automations
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./venv/bin/python -m pytest tests/ -q # must pass before any PR
```

## Pull request process

1. Branch from `main` (`feat/...`, `fix/...`, `docs/...`).
2. Run the full test suite — it takes ~10s. PRs with failing tests are not reviewed.
3. New panel? Follow the pattern: copy the most complete `auth.py`, adjust config, port `api/scraper/CLI/MCP` in that order, CRUD last. Real panels live in the private repo. See `AGENTS.md` rule 7.
4. Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
5. Describe **what** and **why**; the diff shows **how**.

## AI-agent contributors

If you're an AI agent (Hermes, OpenCode, Claude, ...): read [`AGENTS.md`](AGENTS.md) first — it documents the safety architecture, golden rules, and operational guidelines learned from real incidents. Your PRs follow the same rules as human ones, and the test suite is your feedback loop.

## Reporting bugs

Open an issue with: what you did, what you expected, what happened, and the minimal reproduction. **Redact all credentials, tokens, and panel URLs** — issues containing real endpoints or credentials will be closed and deleted.

## License

MIT — see [LICENSE](LICENSE).
