import anyio
from core.ecommerce_x.scraper import sync_product


def _consultar_e_sincronizar_produto(product_id: str) -> str:
    try:
        res = sync_product(product_id)
        return f"Produto {product_id} atualizado com sucesso! Preço: R$ {res['price']}"
    except Exception as e:
        return f"Falha ao sincronizar produto {product_id}: {str(e)}"


def register(mcp):
    @mcp.tool()
    async def consultar_e_sincronizar_produto(product_id: str) -> str:
        """
        Acessa o site e atualiza o banco local com as informações mais recentes do produto.
        Use essa ferramenta quando precisar verificar preço, estoque ou detalhes do item.
        """
        # CR-01: abre browser real (Playwright sync) — precisa sair do event loop.
        return await anyio.to_thread.run_sync(
            _consultar_e_sincronizar_produto, product_id
        )
