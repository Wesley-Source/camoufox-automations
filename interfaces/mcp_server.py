from mcp.server.fastmcp import FastMCP
from core.scrapers.ecommerce_x import sync_product

mcp_app = FastMCP("AutomationHubMCP")

@mcp_app.tool()
def consultar_e_sincronizar_produto(product_id: str) -> str:
    """
    Acessa o site e atualiza o banco local com as informações mais recentes do produto.
    Use essa ferramenta quando precisar verificar preço, estoque ou detalhes do item.
    """
    try:
        res = sync_product(product_id)
        return f"Produto {product_id} atualizado com sucesso! Preço: R$ {res['price']}"
    except Exception as e:
        return f"Falha ao sincronizar produto {product_id}: {str(e)}"
