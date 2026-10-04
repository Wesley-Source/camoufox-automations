import json
from typing import Literal

from core.automations import AUTOMATIONS

from interfaces.mcp.blackbr import register as reg_blackbr
from interfaces.mcp.newmais import register as reg_newmais
from interfaces.mcp.playlist import register as reg_playlist
from interfaces.mcp.ecommerce import register as reg_ecommerce
from interfaces.mcp.sigma import register as reg_sigma
from interfaces.mcp.woodcine import register as reg_woodcine

from mcp.server.fastmcp import FastMCP

mcp_app = FastMCP("AutomationHubMCP")

# Um módulo por site; cada um registra suas tools no servidor.
reg_blackbr(mcp_app)
reg_newmais(mcp_app)
reg_playlist(mcp_app)
reg_ecommerce(mcp_app)
reg_sigma(mcp_app)
reg_woodcine(mcp_app)


AutomationStatus = Literal["ok", "planned", "blocked"]
VALID_STATUSES = ("ok", "planned", "blocked")


@mcp_app.tool()
def listar_automacoes(status: AutomationStatus | None = None) -> str:
    """
    Lista todas as automações disponíveis no hub (status ok|planned|blocked;
    omita para listar todas). Use quando precisar descobrir o que o hub sabe
    fazer e como executar.
    """
    if status and status not in VALID_STATUSES:
        return f"Status inválido: {status}. Opções: {', '.join(VALID_STATUSES)} (ou omita para listar todas)."
    items = [a for a in AUTOMATIONS if not status or a["status"] == status]
    return json.dumps({"total": len(items), "automacoes": items}, ensure_ascii=False, indent=2)
