import json
import os

import typer
from core.scrapers.ecommerce_x import sync_product

cli_app = typer.Typer(help="CLI Hub de Automações")

@cli_app.command("sync-item")
def cli_sync_item(item_id: str):
    """Executa a sincronização de um item específico no terminal."""
    try:
        res = sync_product(item_id)
        typer.secho(f"✔ Sucesso: {res}", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"✖ Erro: {e}", fg=typer.colors.RED)

@cli_app.command("sigma-login")
def cli_sigma_login(save: bool = False):
    """Login no painel Sigma: imprime o token (usa SIGMA_USERNAME/SIGMA_PASSWORD)."""
    username = os.environ.get("SIGMA_USERNAME")
    password = os.environ.get("SIGMA_PASSWORD")
    if not username or not password:
        typer.secho("✖ Defina SIGMA_USERNAME e SIGMA_PASSWORD no ambiente.", fg=typer.colors.RED)
        raise typer.Exit(1)
    from core.scrapers.sigma_lider import login
    try:
        sess = login(username, password)
    except Exception as e:
        typer.secho(f"✖ Login falhou: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"✔ Token: {sess['token']}", fg=typer.colors.GREEN)
    if save:
        with open("sigma_session.json", "w") as f:
            json.dump(sess, f, indent=2)
        typer.secho("✔ Sessão completa salva em sigma_session.json", fg=typer.colors.GREEN)
