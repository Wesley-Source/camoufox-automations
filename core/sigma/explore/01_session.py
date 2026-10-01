"""
Etapa 1 da exploração do painel Sigma — sessão garantida + inventário.

É o "refrescador": garante sessão válida em sigma_session.json
(reutiliza se /api/auth/me confirma; só refaz login se estiver morta —
~10s vs ~1min) e grava o inventário das GET /api/* que a SPA dispara
sozinha no dashboard (~45s de escuta passiva).

Rode: venv/bin/python core/sigma/explore/01_session.py
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import typer  # noqa: E402

from core.sigma.auth import (  # noqa: E402
    ensure_logged_page,
    load_accounts,
    load_session,
    resolve_active_account,
    save_session,
    session_path_for,
)
from core.sigma.explore._guard import install_guard, report_blocked  # noqa: E402

LISTEN_SECONDS = 45
OUT = Path(__file__).parent / "out"


def main():
    OUT.mkdir(exist_ok=True)
    accounts = load_accounts()
    active = resolve_active_account(accounts)
    had = load_session(session_path_for(active["username"] if active else None, accounts)) is not None
    typer.echo(
        "Reutilizando sessão salva..." if had
        else "Sem sessão — logando (pode demorar ~1min)..."
    )
    with ensure_logged_page(guard=install_guard) as s:
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
                # M9: capturas de requests não são sessão — ficam só em out/.
            },
            s.session_path,
            username=s.account,
        )
        (OUT / "dashboard_gets.json").write_text(
            json.dumps(gets, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        spath = s.session_path

    typer.secho(f"\n✔ {len(gets)} GET(s) capturados no carregamento:", fg=typer.colors.GREEN)
    for g in gets:
        typer.echo(f"  {g['status']} {g['url'].replace('https://lideriptv.sigma.st', '')}")
    report_blocked(s.blocked)
    typer.secho(f"✔ Sessão canônica em {spath}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    main()
