import json
import os

import typer

from core.sigma.auth import login

SESSION_FILE = "sigma_session.json"


def register(app: typer.Typer):
    @app.command("sigma-login")
    def cli_sigma_login(save: bool = False):
        """Login no painel Sigma: imprime o token (usa SIGMA_USERNAME/SIGMA_PASSWORD)."""
        username = os.environ.get("SIGMA_USERNAME")
        password = os.environ.get("SIGMA_PASSWORD")
        if not username or not password:
            typer.secho("✖ Defina SIGMA_USERNAME e SIGMA_PASSWORD no ambiente.", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            sess = login(username, password)
        except Exception as e:
            typer.secho(f"✖ Login falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ Token: {sess['token']}", fg=typer.colors.GREEN)
        if save:
            with open(SESSION_FILE, "w") as f:
                json.dump(sess, f, indent=2)
            typer.secho(f"✔ Sessão completa salva em {SESSION_FILE}", fg=typer.colors.GREEN)
