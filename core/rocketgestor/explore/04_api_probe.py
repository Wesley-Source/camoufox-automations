"""
Etapa 4 da exploração do Rocket Gestor — probe de endpoints (GET puro).

Testa candidatos a API/JSON e valida o que responde. Django
server-rendered pode não ter /api/* — o objetivo é descobrir o que existe
(sem mutar NADA: só GET).

Rode: venv/bin/python core/rocketgestor/explore/04_api_probe.py
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

# Candidatos genéricos Django + guesses de domínio (só GET)
CANDIDATES = [
    "/api/", "/api/clients/", "/api/customers/", "/api/v1/",
    "/accounts/profile/", "/clientes/", "/clients/", "/dashboard/",
    "/admin/", "/api/auth/user/", "/api/me/",
]

PROBE_JS = """
async (path) => {
  try {
    const r = await fetch(path, {credentials: "include",
      headers: {"Accept": "application/json"}});
    const ct = r.headers.get("content-type") || "";
    let body = null;
    if (ct.includes("json")) { try { body = await r.json(); } catch (e) {} }
    return {status: r.status, ct, json: !!body,
            snippet: body ? JSON.stringify(body).slice(0, 200)
                          : (await r.text()).slice(0, 120)};
  } catch (e) { return {status: 0, err: String(e).slice(0, 120)}; }
}
"""


def main():
    OUT.mkdir(exist_ok=True)
    results = {}
    with ensure_logged_page(guard=install_guard) as s:
        typer.echo(f"Sondando {len(CANDIDATES)} candidatos (GET puro)...")
        for path in CANDIDATES:
            res = s.page.evaluate(PROBE_JS, path)
            results[path] = res
            mark = "✔" if res.get("status") == 200 else "–"
            typer.echo(f"  {mark} {res.get('status')} {path} "
                       f"[{res.get('ct', '')[:40]}]")
            time.sleep(1)  # pacing (guideline 6: sem request em rajada)
        (OUT / "api_probe.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    ok = [p for p, r in results.items() if r.get("status") == 200]
    typer.secho(f"\n✔ {len(ok)} endpoint(s) respondem 200: {', '.join(ok) or 'nenhum'}",
                fg=typer.colors.GREEN)
    report_blocked(s.blocked)


if __name__ == "__main__":
    main()
