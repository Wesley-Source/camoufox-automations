"""
Etapa 3 da exploração do Rocket Gestor — crawl de rotas internas.

Visita cada link interno descoberto no 02 (uma vez, GET puro — o guard
aborta qualquer mutação) e registra o que aparece em cada rota.

Rode: venv/bin/python core/rocketgestor/explore/03_route_crawl.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.rocketgestor.auth import ROCKET_URL, ensure_logged_page  # noqa: E402
from core.rocketgestor.explore._guard import install_guard, report_blocked  # noqa: E402

OUT = Path(__file__).parent / "out"
SEEN_FILE = OUT / "crawled.json"

ROUTE_JS = """
() => ({
  url: location.href,
  title: document.title,
  headings: [...document.querySelectorAll("h1,h2,h3")].map(h => h.innerText.trim()).slice(0, 8),
  links: [...new Set([...document.querySelectorAll("a[href]")]
      .map(a => a.getAttribute("href"))
      .filter(h => h && h.startsWith("/") && !h.startsWith("//")))],
  tables: document.querySelectorAll("table").length,
  forms: [...document.querySelectorAll("form")].map(f => ({
    action: f.getAttribute("action"), method: (f.method || "get").toUpperCase()})),
})
"""


def main():
    OUT.mkdir(exist_ok=True)
    seen = {}
    if SEEN_FILE.exists():
        seen = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    with ensure_logged_page(guard=install_guard) as s:
        mapa = s.page.evaluate(ROUTE_JS)
        todo = [h for h in mapa["links"]
                if h not in seen and not h.startswith(("/accounts/", "#", "/logout", "/sign-out"))]
        typer.echo(f"{len(todo)} rota(s) novas para visitar (GET puro)...")
        for href in todo:
            try:
                s.page.goto(ROCKET_URL + href, wait_until="domcontentloaded",
                            timeout=45_000)
                time.sleep(3)
                info = s.page.evaluate(ROUTE_JS)
                seen[href] = {"title": info["title"], "headings": info["headings"],
                              "tables": info["tables"], "forms": info["forms"],
                              "sublinks": info["links"]}
                typer.echo(f"  ✔ {href} — {info['title']} "
                           f"({len(info['links'])} links, {info['tables']} tabelas)")
            except Exception as e:
                seen[href] = {"error": str(e)[:120]}
                typer.echo(f"  ✖ {href} — {str(e)[:80]}")
        SEEN_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    typer.secho(f"\n✔ {len(seen)} rota(s) mapeadas no total → {SEEN_FILE}",
                fg=typer.colors.GREEN)
    report_blocked(s.blocked)


if __name__ == "__main__":
    main()
