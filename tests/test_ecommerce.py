from core.scrapers.ecommerce_x import sync_product


def test_sync_product_retorna_estrutura_esperada():
    res = sync_product("TEST_1")

    assert res["id"] == "TEST_1"
    assert res["status"] == "synced"
    assert isinstance(res["price"], float)
    assert isinstance(res["title"], str)
