"""
Etapa 2 da exploração do painel blackbr — mapa do dashboard, sem clicar em nada.

Reutiliza a sessão salva (blackbr_session.json) se válida; senão refaz login
(usa blackbr_session.json de novo). Com guard ativo (read-only estrito),
extrai do DOM:
- todos os links de rota (#/...) do menu lateral = mapa de navegação
- títulos de seção, tabelas e colunas visíveis
- screenshot da página inteira

Saída: out/dashboard_map.json + out/dashboard.png

Rode: venv/bin/python core/blackbr/explore/02_dashboard_map.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.blackbr.auth import ensure_logged_page  # noqa: E402
from core.blackbr.explore._guard import install_guard, report_blocked  # noqa: E402

OUT = Path(__file__).parent / "out"
SETTLE_SECONDS = 20  # tempo pro dashboard terminar de carregar sozinho

# Lê o DOM inteiro de uma vez (um único evaluate, sem clicar em nada).
_DOM_SNAPSHOT = """
() => {
  const links = [...document.querySelectorAll("a[href^='#']")].map(a => ({
    href: a.getAttribute("href"),
    text: (a.innerText || "").trim().replace(/\\s+/g, " ").slice(0, 80),
  })).filter(l => l.href && l.href !== "#");
  const headings = [...document.querySelectorAll("h1,h2,h3")]
    .map(h => (h.innerText || "").trim()).filter(Boolean).slice(0, 40);
  const tables = [...document.querySelectorAll("table")].map(t => ({
    headers: [...t.querySelectorAll("th")].map(th => (th.innerText || "").trim()).slice(0, 30),
    rows: t.querySelectorAll("tbody tr").length,
  }));
  return { title: document.title, links, headings, tables };
}
"""


def main():
    OUT.mkdir(exist_ok=True)
    typer.echo("Abrindo painel blackbr (reutiliza sessão salva se válida)...")
    try:
        with ensure_logged_page(guard=install_guard) as s:
            typer.echo(f"Aguardando {SETTLE_SECONDS}s o dashboard assentar (só leitura)...")
            time.sleep(SETTLE_SECONDS)

            snap = s.page.evaluate(_DOM_SNAPSHOT)
            s.page.screenshot(path=str(OUT / "dashboard.png"), full_page=True)

            # Rotas únicas (a mesma rota aparece no menu e em breadcrumbs).
            routes = {}
            for l in snap["links"]:
                routes.setdefault(l["href"], l["text"])

            gets = [
                {k: c[k] for k in ("method", "url", "status")}
                for c in s.captured
                if c["method"] == "GET"
            ]
            data = {
                "page_title": snap["title"],
                "routes": routes,
                "headings": snap["headings"],
                "tables": snap["tables"],
                "dashboard_gets": gets,
                "blocked_by_guard": s.blocked,
            }
            (OUT / "dashboard_map.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    except RuntimeError as e:
        typer.secho(f"✖ {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho(f"\n✔ {len(routes)} rotas de navegação descobertas:", fg=typer.colors.GREEN)
    for href, text in sorted(routes.items()):
        typer.echo(f"  {href:45s} {text[:40]}")
    typer.secho(f"\n✔ Tabelas visíveis: {len(snap['tables'])}", fg=typer.colors.GREEN)
    for t in snap["tables"]:
        typer.echo(f"  {t['rows']} linhas | colunas: {', '.join(t['headers'][:10])}")
    typer.secho(f"✔ {len(gets)} GET(s) capturados no carregamento.", fg=typer.colors.GREEN)
    report_blocked(s.blocked)
    typer.secho(f"✔ Mapa em {OUT / 'dashboard_map.json'} (+ dashboard.png)", fg=typer.colors.GREEN)


if __name__ == "__main__":
    main()
