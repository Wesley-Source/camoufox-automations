import typer

from core.ecommerce_x.scraper import sync_product


def register(app: typer.Typer):
    @app.command("sync-item")
    def cli_sync_item(item_id: str):
        """Executa a sincronização de um item específico no terminal."""
        try:
            res = sync_product(item_id)
            typer.secho(f"✔ Sucesso: {res}", fg=typer.colors.GREEN)
        except Exception as e:
            typer.secho(f"✖ Erro: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)  # CR-11: falha não pode sair como sucesso
