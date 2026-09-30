"""
Etapa 3 da exploração do painel Sigma — crawleo cuidadoso das rotas.

Lê out/dashboard_map.json (gerado pelo 02) e visita cada rota UMA a uma,
por navegação de hash (equivalente a GET — nada é clicado nem enviado):

- Guard ativo: POST/PUT/PATCH/DELETE abortados no nível do browser.
- Blocklist: rotas com settings/user/admin/billing/finance/payment etc.
  ficam FORA do crawl (mapeadas, mas não visitadas).
- --max N (padrão 5): visita no máximo N rotas novas por execução —
  descobre pouco por vez; revise out/routes/ antes de rodar de novo.
- Resumível: rotas já capturadas são puladas.
- Parada imediata em anomalia: redireção pra login, status 5xx ou
  desafio Cloudflare — salva o que deu e sai com erro.

Saída: out/routes/<slug>.json + <slug>.png por rota.

Rode: SIGMA_USERNAME=... SIGMA_PASSWORD=... venv/bin/python core/sigma/explore/03_route_crawl.py
"""
import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.auth import SIGMA_URL, logged_page  # noqa: E402
from core.sigma.explore._guard import install_guard, report_blocked  # noqa: E402

OUT = Path(__file__).parent / "out"
ROUTES_OUT = OUT / "routes"
MAP_FILE = OUT / "dashboard_map.json"
SETTLE_SECONDS = 8

# ponytail: blocklist por regex de URL — apertar conforme o mapa real aparecer
BLOCKLIST = re.compile(
    r"setting|config|user|admin|billing|invoice|finance|payment|"
    r"password|profile|api[-_]?key|token|reseller|notice",
    re.I,
)

_DOM_SNAPSHOT = """
() => ({
  title: document.title,
  headings: [...document.querySelectorAll("h1,h2,h3")]
    .map(h => (h.innerText || "").trim()).filter(Boolean).slice(0, 30),
  tables: [...document.querySelectorAll("table")].map(t => ({
    headers: [...t.querySelectorAll("th")].map(th => (th.innerText || "").trim()).slice(0, 30),
    rows: t.querySelectorAll("tbody tr").length,
  })),
})
"""


def slug_for(route: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", route.lower()).strip("-") or "root"


def looks_like_anomaly(s) -> str | None:
    """Retorna o motivo se a sessão/página indicar problema, senão None."""
    if "sign-in" in s.page.url:
        return "sessão perdida (redirecionado pro login)"
    for c in s.captured:
        if c["status"] >= 500:
            return f"status {c['status']} em {c['url']}"
    title = s.page.title().lower()
    if "attention required" in title or "just a moment" in title:
        return "desafio Cloudflare detectado"
    return None


def main(
    max_routes: int = typer.Option(5, help="Máximo de rotas NOVAS por execução."),
    delay: float = typer.Option(3.0, help="Pausa (s) entre rotas."),
):
    username = os.environ.get("SIGMA_USERNAME")
    password = os.environ.get("SIGMA_PASSWORD")
    if not username or not password:
        typer.secho("✖ Defina SIGMA_USERNAME e SIGMA_PASSWORD.", fg=typer.colors.RED)
        raise typer.Exit(1)
    if not MAP_FILE.exists():
        typer.secho(f"✖ {MAP_FILE} não existe — rode o 02_dashboard_map.py antes.", fg=typer.colors.RED)
        raise typer.Exit(1)

    routes = sorted(json.loads(MAP_FILE.read_text(encoding="utf-8"))["routes"])
    allowed = [r for r in routes if not BLOCKLIST.search(r)]
    skipped_bl = [r for r in routes if BLOCKLIST.search(r)]
    ROUTES_OUT.mkdir(parents=True, exist_ok=True)

    typer.echo(f"{len(routes)} rotas no mapa | {len(skipped_bl)} na blocklist | {len(allowed)} liberadas")
    todo = [
        r for r in allowed
        if not (ROUTES_OUT / f"{slug_for(r)}.json").exists()
    ][:max_routes]
    if not todo:
        typer.secho("✔ Nada novo a crawlear (todas as liberadas já têm captura).", fg=typer.colors.GREEN)
        return

    done, anomaly = [], None
    with logged_page(username, password, guard=install_guard) as s:
        n_before = len(s.captured)
        for route in todo:
            typer.echo(f"\n→ {route}")
            s.page.evaluate(f"() => location.hash = '{route}'")
            time.sleep(SETTLE_SECONDS)

            if reason := looks_like_anomaly(s):
                anomaly = reason
                typer.secho(f"✖ Anomalia: {reason} — parando.", fg=typer.colors.RED)
                break

            snap = s.page.evaluate(_DOM_SNAPSHOT)
            new_gets = [
                {k: c[k] for k in ("method", "url", "status")}
                for c in s.captured[n_before:]
                if c["method"] == "GET"
            ]
            n_before = len(s.captured)
            s.page.screenshot(path=str(ROUTES_OUT / f"{slug_for(route)}.png"), full_page=True)
            (ROUTES_OUT / f"{slug_for(route)}.json").write_text(
                json.dumps(
                    {"route": route, "page_title": snap["title"], "headings": snap["headings"],
                     "tables": snap["tables"], "gets": new_gets, "blocked_by_guard": s.blocked},
                    indent=2, ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            done.append(route)
            typer.secho(
                f"  ✔ {len(new_gets)} GET(s), {len(snap['tables'])} tabela(s)",
                fg=typer.colors.GREEN,
            )
            time.sleep(random.uniform(delay, delay + 2))

    typer.secho(f"\n✔ {len(done)} rota(s) capturada(s) em {ROUTES_OUT}:", fg=typer.colors.GREEN)
    for r in done:
        typer.echo(f"  {r}")
    report_blocked(s.blocked)
    if anomaly:
        typer.secho(f"✖ Parado por: {anomaly}", fg=typer.colors.RED)
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
