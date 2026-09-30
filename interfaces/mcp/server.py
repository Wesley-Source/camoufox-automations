from interfaces.mcp.ecommerce import register as reg_ecommerce
from interfaces.mcp.sigma import register as reg_sigma

from mcp.server.fastmcp import FastMCP

mcp_app = FastMCP("AutomationHubMCP")

# Um módulo por site; cada um registra suas tools no servidor.
reg_ecommerce(mcp_app)
reg_sigma(mcp_app)
