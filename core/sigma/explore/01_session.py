"""
Etapa 1 da exploração do painel Sigma — sessão FRESCA + primeiro inventário.

É o "refrescador": sempre faz login completo (ignora sessão salva) e
grava a sessão canônica em sigma_session.json para os outros scripts
reutilizarem. Também fica ~45s no dashboard ESCUTANDO as GET /api/* que
a SPA dispara sozinha.

Rode: SIGMA_USERNAME=... SIGMA_PASSWORD=... venv/bin/python core/sigma/explore/01_session.py
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.auth import (  # noqa: E402
    SESSION_FILE,
    logged_page,
    save_session,
)
from core.sigma.explore._guard import install_guard, report_blocked  # noqa: E402

LISTEN_SECONDS = 45
OUT = Path(__file__).parent / "out"


def main():
    username = os.environ.get("SIGMA_USERNAME")
    password = os.environ.get("SIGMA_PASSWORD")
    if not username or not password:
        typer.secho("✖ Defina SIGMA_USERNAME e SIGMA_PASSWORD.", fg=typer.colors.RED)
        raise typer.Exit(1)

    OUT.mkdir(exist_ok=True)
    typer.echo("Logando no painel Sigma (login completo, pode demorar ~1min)...")
    with logged_page(username, password, guard=install_guard) as s:
        typer.secho(f"✔ Token OK: {s.token[:20]}...", fg=typer.colors.GREEN)
        typer.echo(f"Escutando o dashboard por {LISTEN_SECONDS}s (só leitura)...")
        time.sleep(LISTEN_SECONDS)

        gets = [
            {k: c[k] for k in ("method", "url", "status")}
            for c in s.captured
            if c["method"] == "GET"
        ]
        save_session(
            {
                "token": s.token,
                "cookies": s.page.context.cookies(),
                "local_storage": s.page.evaluate(
                    "() => Object.fromEntries(Object.entries(localStorage))"
                ),
                "dashboard_gets": gets,
            },
            SESSION_FILE,
        )
        (OUT / "dashboard_gets.json").write_text(
            json.dumps(gets, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    typer.secho(f"\n✔ {len(gets)} GET(s) capturados no carregamento:", fg=typer.colors.GREEN)
    for g in gets:
        typer.echo(f"  {g['status']} {g['url'].replace('https://lideriptv.sigma.st', '')}")
    report_blocked(s.blocked)
    typer.secho(f"✔ Sessão canônica em {SESSION_FILE}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    main()
