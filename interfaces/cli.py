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
