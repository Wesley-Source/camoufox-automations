"""Servidor MCP do hub — framework sempre; sites reais quando presentes.

O framework roda sozinho (exemplo ecommerce_x + inventário). Os sites reais
vivem no repo PRIVADO `camoufox-panels`: clone-o lado a lado deste e rode o
`join.sh` dele (symlinks) — ou copie as pastas `core/<site>/` +
`interfaces/{cli,mcp}/<site>.py` pra cá. Sem eles, as tools `<op>_<site>`
não são registradas e um warning vai pro stderr (nunca stdout — stdio MCP).
"""
import logging
import json
from typing import Literal

from core.automations import AUTOMATIONS

from interfaces.mcp.ecommerce import register as reg_ecommerce

from mcp.server.fastmcp import FastMCP

mcp_app = FastMCP("AutomationHubMCP")

# Um módulo por site; cada um registra suas tools no servidor.
# Sites ausentes NÃO derrubam o servidor — warning no stderr e segue o baile.
_SITE_REGS = (
    ("blackbr", "interfaces.mcp.blackbr"),
    ("newmais", "interfaces.mcp.newmais"),
    ("rocketgestor", "interfaces.mcp.rocketgestor"),
    ("playlist", "interfaces.mcp.playlist"),
    ("sigma", "interfaces.mcp.sigma"),
    ("woodcine", "interfaces.mcp.woodcine"),
)
_missing = []
for _name, _modname in _SITE_REGS:
    try:
        _reg = __import__(_modname, fromlist=["register"]).register
    except ImportError:
        _missing.append(_name)
    else:
        _reg(mcp_app)

if _missing:
    logging.getLogger("interfaces.mcp").warning(
        "site module not installed — clone camoufox-panels e adicione ao "
        "PYTHONPATH, ou copie as pastas para core/ (veja README): sites "
        "ausentes: %s", ", ".join(_missing),
    )


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
