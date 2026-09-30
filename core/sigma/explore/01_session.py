"""
Etapa 1 da exploração do painel Sigma — sessão fresca + primeiro inventário.

O que faz (tudo read-only):
1. Loga (o POST de auth é a única mutação de rede, e é inofensiva).
2. Instala o guard (bloqueia POST/PUT/PATCH/DELETE daqui pra frente).
3. Fica ~45s parado no dashboard ESCUTANDO: registra toda GET /api/*
   que a SPA dispara sozinha ao carregar.
4. Salva sessão + inventário em out/session.json.

Rode: SIGMA_USERNAME=... SIGMA_PASSWORD=... venv/bin/python core/sigma/explore/01_session.py
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.auth import logged_page  # noqa: E402
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
    typer.echo("Logando no painel Sigma (pode demorar ~1min)...")
    with logged_page(username, password, guard=install_guard) as s:
        typer.secho(f"✔ Token OK: {s.token[:20]}...", fg=typer.colors.GREEN)
        typer.echo(f"Escutando o dashboard por {LISTEN_SECONDS}s (só leitura)...")
        time.sleep(LISTEN_SECONDS)

        gets = [
            {k: c[k] for k in ("method", "url", "status")}
            for c in s.captured
            if c["method"] == "GET"
        ]
        data = {
            "token": s.token,
            "cookies": s.page.context.cookies(),
            "local_storage": s.page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            ),
            "dashboard_gets": gets,
            "blocked_by_guard": s.blocked,
        }
        (OUT / "session.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    typer.secho(f"\n✔ {len(gets)} GET(s) capturados no carregamento:", fg=typer.colors.GREEN)
    for g in gets:
        typer.echo(f"  {g['status']} {g['url'].replace('https://lideriptv.sigma.st', '')}")
    report_blocked(s.blocked)
    typer.secho(f"✔ Salvo em {OUT / 'session.json'}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    main()
