"""
Etapa 3 da exploração do painel Sigma — crawleo cuidadoso das rotas.

Reutiliza a sessão salva (sigma_session.json) se válida; senão refaz login.
Lê out/dashboard_map.json (gerado pelo 02) e visita cada rota UMA a uma,
por navegação de hash (equivale a GET — nada é clicado nem enviado):

- Guard ativo: POST/PUT/PATCH/DELETE abortados no nível do browser.
- Blocklist: rotas com settings/user/admin/billing/finance/payment etc.
  ficam FORA do crawl (mapeadas, mas não visitadas).
- --max N (padrão 5): visita no máximo N rotas novas por execução —
  descobre pouco por vez; revise out/routes/ antes de rodar de novo.
- Resumível: rotas já capturadas são puladas.
- Parada imediata em anomalia: redireção pra login, status 5xx ou
  desafio Cloudflare — salva o que deu e sai com erro.

Saída: out/routes/<slug>.json + <slug>.png por rota.

Rode: venv/bin/python core/sigma/explore/03_route_crawl.py
"""
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.auth import SIGMA_URL, ensure_logged_page  # noqa: E402
from core.sigma.explore._guard import install_guard, report_blocked  # noqa: E402

OUT = Path(__file__).parent / "out"
ROUTES_OUT = OUT / "routes"
# Rotas vêm do DOM do painel; o regex barra href estranho antes do evaluate
# (evita injeção de JS via location.hash).
ROUTE_RE = re.compile(r"^#[A-Za-z0-9/_-]+$")
MAP_FILE = OUT / "dashboard_map.json"
SETTLE_SECONDS = 8
DATA_GRACE = 6  # pós-router: janela pros GETs de dados da rota

# ponytail: blocklist conservadora pós-mapa do 02 — tudo que é formulário,
# ferramenta de mutação, configuração ou messaging fica fora; liberar rota a
# rota depois de revisar as capturas.
BLOCKLIST = re.compile(
    r"setting|config|user|admin|billing|invoice|finance|payment|"
    r"password|profile|api[-_]?key|token|reseller|notice"
    r"|sign[-_]?(out|up)|logout"                     # mataria a sessão
    r"|credit|purchase|migrat|renew|integration|system"  # ferramentas/financeiro
    r"|\bedit\b|/add|create|delete"                  # formulários de escrita
    r"|botbot|message|reminder|ticket",              # messaging/envios
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


def _wait_route_ready(s, route: str, expected: str, timeout_s: int = 20) -> bool:
    """
    Espera o router Vue assentar: hash certo + título esperado (o mapa do 02
    fornece o texto do menu, que o SPA usa de título). Tolerante a timeout —
    devolve False e o crawl segue com o wait fixo de graça.
    """
    try:
        s.page.wait_for_function(
            "([r, prefix]) => location.hash === r && document.title.startsWith(prefix)",
            [route, expected or ""],
            timeout=timeout_s * 1000,
        )
        return True
    except Exception:
        return False


def looks_like_anomaly(s) -> str | None:
    """Retorna o motivo se a sessão/página indicar problema, senão None."""
    if "sign-in" in s.page.url:
        return "sessão perdida (redirecionado pro login)"
    for c in s.captured:
        if c["status"] >= 500:
            return f"status {c['status']} em {c['url']}"
        if c["status"] == 401:
            return "401 — token morto no meio do crawl (captura envenenada)"
    title = s.page.title().lower()
    if "attention required" in title or "just a moment" in title:
        return "desafio Cloudflare detectado"
    return None


def main(
    max_routes: int = typer.Option(5, help="Máximo de rotas NOVAS por execução."),
    delay: float = typer.Option(3.0, help="Pausa (s) entre rotas."),
):
    if not MAP_FILE.exists():
        typer.secho(f"✖ {MAP_FILE} não existe — rode o 02_dashboard_map.py antes.", fg=typer.colors.RED)
        raise typer.Exit(1)

    route_map = json.loads(MAP_FILE.read_text(encoding="utf-8"))["routes"]
    allowed = sorted(r for r in route_map if not BLOCKLIST.search(r))
    skipped_bl = sorted(r for r in route_map if BLOCKLIST.search(r))
    ROUTES_OUT.mkdir(parents=True, exist_ok=True)

    typer.echo(f"{len(route_map)} rotas no mapa | {len(skipped_bl)} na blocklist | {len(allowed)} liberadas")
    todo = [
        (r, route_map[r]) for r in allowed
        if not (ROUTES_OUT / f"{slug_for(r)}.json").exists()
    ][:max_routes]
    if not todo:
        typer.secho("✔ Nada novo a crawlear (todas as liberadas já têm captura).", fg=typer.colors.GREEN)
        return

    done, anomaly, blocked, s_block = [], None, [], []
    typer.echo("Abrindo painel (reutiliza sessão salva se válida)...")
    try:
        with ensure_logged_page(guard=install_guard) as s:
            blocked = s.blocked
            n_before = len(s.captured)
            for route, expected in todo:
                typer.echo(f"\n→ {route}")
                if not ROUTE_RE.match(route):
                    anomaly = f"rota com caracteres inesperados: {route!r}"
                    typer.secho(f"✖ {anomaly} — parando (evita injeção no evaluate).", fg=typer.colors.RED)
                    break
                s.page.evaluate(f"() => location.hash = '{route}'")
                _wait_route_ready(s, route, expected)
                time.sleep(DATA_GRACE)  # GETs de dados da rota disparam depois do render

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
                if not any(g["status"] == 200 for g in new_gets):
                    # Captura envenenada (ex.: 401 na rota) NÃO é gravada —
                    # assim o crawl resumível re-visita na próxima execução.
                    typer.secho(f"  ⚠ nenhum GET 200 em {route} — captura descartada.", fg=typer.colors.YELLOW)
                    time.sleep(random.uniform(delay, delay + 2))
                    continue
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
            s_block = s.blocked
    except RuntimeError as e:
        typer.secho(f"✖ {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho(f"\n✔ {len(done)} rota(s) capturada(s) em {ROUTES_OUT}:", fg=typer.colors.GREEN)
    for r in done:
        typer.echo(f"  {r}")
    report_blocked(s_block)
    if anomaly:
        typer.secho(f"✖ Parado por: {anomaly}", fg=typer.colors.RED)
        raise typer.Exit(1)


if __name__ == "__main__":
    typer.run(main)  # parseia --max/--delay mesmo rodando o arquivo direto
