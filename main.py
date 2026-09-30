from interfaces.mcp_server import mcp_app
from interfaces.cli import cli_app
from core.database import init_db
import sys

if __name__ == "__main__":
    init_db()  # Garante que as tabelas existem

    # Se passar 'mcp' como argumento, roda o servidor MCP.
    # Caso contrário, roda a CLI Typer.
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        mcp_app.run()
    else:
        cli_app()
