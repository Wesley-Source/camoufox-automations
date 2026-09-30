import typer

cli_app = typer.Typer(help="CLI Hub de Automações")

# Um módulo por site; cada um registra seus comandos no app.
from interfaces.cli import ecommerce, sigma  # noqa: E402

ecommerce.register(cli_app)
sigma.register(cli_app)
