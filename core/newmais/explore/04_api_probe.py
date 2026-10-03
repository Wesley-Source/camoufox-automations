"""
Etapa 4 da exploração do painel Sigma — probe da API (somente GET + Bearer).

Em vez de navegar em páginas de risco, fala DIRETO com a API: cada endpoint
conhecido é consultado com GET + Authorization: Bearer <token> via fetch no
contexto da página (o browser resolve o DNS/Cloudflare; o guard continua
ativo bloqueando qualquer POST/PUT/PATCH/DELETE que o SPA tentar).

Endpoints: descobertos no crawl (02/03) + confirmados manualmente.
Saída: out/api/<slug>.json com {url, status, body}.

Rode: venv/bin/python core/sigma/explore/04_api_probe.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.newmais.auth import NEWMAIS_API, ensure_logged_page  # noqa: E402
from core.newmais.explore._guard import install_guard, report_blocked  # noqa: E402

OUT = Path(__file__).parent / "out" / "api"
_BODY_CAP = 200_000  # ponytail: trunca corpos gigantes (clientes p/ paginar depois)

# Somente leitura. top10 usa a janela de datas vista no crawl do dashboard.
ENDPOINTS = [
    "/api/auth/me",
    "/api/settings",
    "/api/settings/public",
    "/api/notices/list",
    "/api/resellers/list",
    "/api/customers?page=1",
    "/api/customers?page=2",
    "/api/customers/expiring",
    "/api/customers/statistics",
    "/api/customers/statistics/top10"
    "?from_date=2026-08-30T03:00:00.000Z&to_date=2026-09-30T02:59:59.999Z",
    "/api/statistics/customers",
    "/api/statistics/resellers",
    "/api/dashboard/charts/new-customers",
    "/api/dashboard/charts/customer-retention",
    "/api/dashboard/charts/revenue-forecast",
    "/api/dashboard/charts/lost-revenue",
    "/api/dashboard/metrics/recovery",
    "/api/dashboard/ai-analysis",
]

_FETCH = """async ([path, token]) => {
    const r = await fetch(path, {headers: {Authorization: 'Bearer ' + token}});
    const text = await r.text();
    return {status: r.status, body: text};
}"""


def slug_for(path: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return s[:80] or "root"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    typer.echo("Abrindo painel (reutiliza sessão salva se válida)...")
    try:
        with ensure_logged_page(guard=install_guard) as s:
            results = []
            for ep in ENDPOINTS:
                url = ep if ep.startswith("/api") else NEWMAIS_API + ep
                try:
                    r = s.page.evaluate(_FETCH, [url, s.token])
                    status, body = r["status"], r["body"][:_BODY_CAP]
                except Exception as e:
                    status, body = 0, f"erro no fetch: {e}"
                data = {"url": NEWMAIS_API + ep.replace("/api", "", 1) if ep.startswith("/api") else ep,
                        "status": status, "body": body}
                (OUT / f"{slug_for(ep)}.json").write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                results.append((ep, status))
                typer.secho(f"  {status or 'ERR':>4} {ep}", fg=typer.colors.GREEN if status == 200 else typer.colors.RED)
            blocked = s.blocked
    except RuntimeError as e:
        typer.secho(f"✖ {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    ok = sum(1 for _, st in results if st == 200)
    typer.secho(f"\n✔ {ok}/{len(results)} endpoints responderam 200 → {OUT}", fg=typer.colors.GREEN)
    report_blocked(blocked)


if __name__ == "__main__":
    typer.run(main)
