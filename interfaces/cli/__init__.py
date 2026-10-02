import typer

from core.automations import AUTOMATIONS

cli_app = typer.Typer(help="CLI Hub de Automações")

# Um módulo por site; cada um registra seus comandos no app.
from interfaces.cli import blackbr, ecommerce, sigma, woodcine  # noqa: E402

blackbr.register(cli_app)
ecommerce.register(cli_app)
sigma.register(cli_app)
woodcine.register(cli_app)


_STATUS_COR = {"ok": typer.colors.GREEN, "planned": typer.colors.YELLOW, "blocked": typer.colors.RED}


@cli_app.command("automations")
def cli_automations(status: str = None):
    """Lista todas as automações do hub (ok / planned / blocked)."""
    items = [a for a in AUTOMATIONS if not status or a["status"] == status]
    if status and status not in _STATUS_COR:
        typer.secho(f"✖ status inválido: {status} (use ok|planned|blocked)", fg=typer.colors.RED)
        raise typer.Exit(1)
    for a in items:
        cor = _STATUS_COR[a["status"]]
        typer.secho(f"[{a['status'].upper():7s}] {a['id']}", fg=cor)
        typer.echo(f"    {a['what']}")
        typer.secho(f"    → {a['run']}", fg=typer.colors.BRIGHT_BLACK)
    typer.echo(f"\n{len(items)} automação(ões).")
