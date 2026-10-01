import json

from core.automations import AUTOMATIONS

from interfaces.mcp.ecommerce import register as reg_ecommerce
from interfaces.mcp.sigma import register as reg_sigma

from mcp.server.fastmcp import FastMCP

mcp_app = FastMCP("AutomationHubMCP")

# Um módulo por site; cada um registra suas tools no servidor.
reg_ecommerce(mcp_app)
reg_sigma(mcp_app)


VALID_STATUSES = ("ok", "planned", "blocked")


@mcp_app.tool()
def listar_automacoes(status: str = None) -> str:
    """
    Lista todas as automações disponíveis no hub (status ok|planned|blocked).
    Use quando precisar descobrir o que o hub sabe fazer e como executar.
    """
    if status and status not in VALID_STATUSES:
        return f"Status inválido: {status}. Opções: {', '.join(VALID_STATUSES)} (ou omita para listar todas)."
    items = [a for a in AUTOMATIONS if not status or a["status"] == status]
    return json.dumps({"total": len(items), "automacoes": items}, ensure_ascii=False, indent=2)
