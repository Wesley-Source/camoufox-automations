"""
Etapa 2 da exploração do Rocket Gestor — mapa do dashboard.

Com a sessão garantida (rode 01 primeiro), extrai a estrutura do app:
links do menu, tabelas, formulários e rotas visíveis. Só leitura.

Rode: venv/bin/python core/rocketgestor/explore/02_dashboard_map.py
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

MAP_JS = """
() => {
  const links = [...document.querySelectorAll("a[href]")]
    .map(a => ({href: a.getAttribute("href"), text: (a.innerText || "").trim().slice(0, 60)}))
    .filter(l => l.href && !l.href.startsWith("http") || l.href.startsWith("/"));
  const uniq = {};
  links.forEach(l => uniq[l.href] = l.text);
  const tables = [...document.querySelectorAll("table")].map(t => ({
    headers: [...t.querySelectorAll("th")].map(th => th.innerText.trim()),
    rows: t.querySelectorAll("tbody tr").length,
  }));
  const forms = [...document.querySelectorAll("form")].map(f => ({
    action: f.getAttribute("action"), method: (f.method || "get").toUpperCase(),
    inputs: [...f.querySelectorAll("input,select,textarea")].map(i => i.name).filter(Boolean),
  }));
  const buttons = [...document.querySelectorAll("button, input[type=submit]")]
    .map(b => (b.innerText || b.value || "").trim()).filter(Boolean).slice(0, 30);
  return {url: location.href, title: document.title,
          links: uniq, tables, forms, buttons};
}
"""


def main():
    OUT.mkdir(exist_ok=True)
    with ensure_logged_page(guard=install_guard) as s:
        time.sleep(5)  # deixa o dashboard assentar
        mapa = s.page.evaluate(MAP_JS)
        (OUT / "dashboard_map.json").write_text(
            json.dumps(mapa, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        s.page.screenshot(path=str(OUT / "dashboard.png"), full_page=True)

    typer.secho(f"✔ {mapa['title']} — {len(mapa['links'])} link(s), "
                f"{len(mapa['tables'])} tabela(s), {len(mapa['forms'])} form(s)",
                fg=typer.colors.GREEN)
    for href, text in list(mapa["links"].items())[:25]:
        typer.echo(f"  {href}  {text}")
    for t in mapa["tables"][:10]:
        typer.echo(f"  tabela: {t['rows']} linhas | {', '.join(t['headers'][:8])}")
    report_blocked(s.blocked)
    typer.secho("✔ Mapa em core/rocketgestor/explore/out/dashboard_map.json",
                fg=typer.colors.GREEN)


if __name__ == "__main__":
    main()
