"""
Etapa 1 da exploração do Rocket Gestor — sessão garantida + inventário.

Garante sessão válida em rocketgestor_session.json (cookies Django;
reutiliza se ainda logado, só refaz login se morto) e grava o inventário
de requests que o app dispara sozinho no dashboard (~45s passivos).

Rode: venv/bin/python core/rocketgestor/explore/01_session.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.rocketgestor.auth import (  # noqa: E402
    ROCKET_URL,
    ensure_logged_page,
    load_accounts,
    load_session,
    resolve_active_account,
)
from core.rocketgestor.explore._guard import install_guard, report_blocked  # noqa: E402

LISTEN_SECONDS = 45
OUT = Path(__file__).parent / "out"


def main():
    OUT.mkdir(exist_ok=True)
    accounts = load_accounts()
    active = resolve_active_account(accounts)
    had = load_session() is not None
    typer.echo(
        "Reutilizando sessão salva..." if had
        else "Sem sessão — logando (pode demorar ~1min)..."
    )
    with ensure_logged_page(guard=install_guard) as s:
        typer.secho(f"✔ Sessão OK: {s.token}", fg=typer.colors.GREEN)
        typer.echo(f"Escutando o app por {LISTEN_SECONDS}s (só leitura)...")
        time.sleep(LISTEN_SECONDS)

        gets = [
            {k: c[k] for k in ("method", "url", "status")}
            for c in s.captured
            if c["method"] == "GET"
        ]
        (OUT / "dashboard_gets.json").write_text(
            json.dumps(gets, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        spath = s.session_path

    typer.secho(f"\n✔ {len(gets)} GET(s) capturados no carregamento:", fg=typer.colors.GREEN)
    for g in gets:
        typer.echo(f"  {g['status']} {g['url'].replace(ROCKET_URL, '')}")
    report_blocked(s.blocked)
    typer.secho(f"✔ Sessão canônica em {spath}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    main()
