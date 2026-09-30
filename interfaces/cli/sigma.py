import json
import os

import typer

from core.sigma.auth import SESSION_FILE, login
from core.sigma.api import open_client
from core.sigma.scraper import SYNCERS, entities_summary, sync_all, sync_customers


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

    @app.command("sigma-sync")
    def cli_sigma_sync(
        what: str = typer.Option("customers", help="customers|expiring|dashboard|resellers|statistics|all"),
        pages: int = typer.Option(5, help="Páginas de clientes (quando aplicável)."),
        per_page: int = typer.Option(100, help="Clientes por página (cap real da API: 100)."),
    ):
        """Sincroniza dados do painel Sigma para o banco local (read-only)."""
        if what not in (*SYNCERS, "all"):
            typer.secho(f"✖ 'what' inválido: {what}. Opções: {', '.join([*SYNCERS, 'all'])}", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with open_client() as client:
                if what == "all":
                    results = sync_all(client, pages, per_page)
                elif what == "customers":
                    results = [sync_customers(client, pages, per_page)]
                else:
                    results = [SYNCERS[what](client)]
        except Exception as e:
            typer.secho(f"✖ Sync falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        for r in results:
            extra = f" ({r['pages']} pág.)" if "pages" in r else ""
            typer.secho(f"✔ {r['what']}: {r['synced']} registro(s){extra}", fg=typer.colors.GREEN)

    @app.command("sigma-status")
    def cli_sigma_status():
        """Validade do token/painel Sigma + contagem do banco local."""
        try:
            with open_client() as client:
                me = client.me()
        except Exception as e:
            typer.secho(f"✖ Sigma inacessível: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        expiry = me.get("membership_expiry_date")
        typer.secho(f"✔ Usuário: {me.get('username')} | Painel expira: {expiry or 'ilimitado'}", fg=typer.colors.GREEN)
        for kind, n in entities_summary().items():
            typer.echo(f"  {kind:18s} {n}")
