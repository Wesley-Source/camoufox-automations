from core.browser import BrowserEngine
from core.database import save_raw_and_clean

def sync_product(product_id: str) -> dict:
    """Extrai os dados de um produto e salva no banco de dados local."""
    url = f"https://httpbin.org/json"  # Substitua pela URL real do site

    with BrowserEngine.get_page() as page:
        page.goto(url)
        # Captura o conteúdo ou JSON da resposta
        content = page.evaluate("() => JSON.parse(document.body.innerText)")

        # Exemplo simulado de extração de dados
        title = "Produto Teste"
        price = 99.90

        # Salva via ELT
        save_raw_and_clean(
            url=url,
            external_id=product_id,
            title=title,
            price=price,
            raw_data=content
        )

        return {"id": product_id, "title": title, "price": price, "status": "synced"}
