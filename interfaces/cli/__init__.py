"""Registry CLI do hub — framework sempre; sites reais quando presentes.

O framework roda sozinho (exemplo ecommerce_x + inventário). Os sites reais
vivem no repo PRIVADO `camoufox-panels`: clone-o lado a lado deste e rode o
`join.sh` dele (symlinks) — ou copie as pastas `core/<site>/` +
`interfaces/{cli,mcp}/<site>.py` pra cá. Sem eles, os comandos `<site>-*`
não existem e o aviso abaixo aparece no `--help`.
"""
import logging
import typer

from core.automations import AUTOMATIONS

cli_app = typer.Typer(help="CLI Hub de Automações")

from interfaces.cli import ecommerce  # noqa: E402  (exemplo httpbin — vem com o framework)
from interfaces.cli import _ops  # noqa: E402  (export/alerts/doctor/snapshot — framework)

ecommerce.register(cli_app)
_ops.register(cli_app)

# Um módulo por site; cada um registra seus comandos no app.
# Sites ausentes NÃO derrubam o hub — aviso amigável e segue o baile.
_SITES = ("blackbr", "newmais", "rocketgestor", "sigma", "woodcine")
_missing = []
for _name in _SITES:
    try:
        _mod = __import__(f"interfaces.cli.{_name}", fromlist=["register"])
    except ImportError:
        _missing.append(_name)
    else:
        _mod.register(cli_app)

if _missing:
    _NOTICE = (
        "site module not installed — clone camoufox-panels e adicione ao "
        "PYTHONPATH, ou copie as pastas para core/ (veja README: Connecting real panels)"
    )
    logging.getLogger("interfaces.cli").warning(
        "sites ausentes (%s): %s", ", ".join(_missing), _NOTICE
    )
    cli_app.info.help = (cli_app.info.help or "") + (
        f"\n\n⚠ Sites reais não instalados ({', '.join(_missing)}): "
        + _NOTICE
        + "."
    )


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
