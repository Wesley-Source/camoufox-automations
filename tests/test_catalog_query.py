"""Commit "servers/packages + busca": catálogo, projeção segura e busca."""
import json

import pytest

import core.database as database
from core.database import list_entities, search_entities
from core.sigma.api import project_customer, search_customers
from core.sigma.scraper import sync_servers_packages


class FakeCatalogClient:
    def servers(self):
        return [{"id": "srv1", "name": "Serv A"}, {"id": "srv2", "name": "Serv B"}]

    def packages(self):
        return [{"id": "pkg1", "name": "Pack 1", "server_id": "srv1"},
                {"id": "pkg2", "name": "Pack 2", "server_id": "srv2"},
                {"name": "sem_id"}]  # M4: pula row sem id


class FakeLaravelCatalogClient:
    """Formato REAL do painel: envelope Laravel {"data": [...]}.

    Achado ao vivo na VPS — iterar o envelope como lista percorre as chaves
    do dict e explode com "'str' object has no attribute 'get'".
    """

    def servers(self):
        return {"data": [{"id": "srvX", "name": "LIDER ALPHA"}]}

    def packages(self):
        return {"data": [{"id": "pkgX", "name": "Pack X", "server_id": "srvX"}]}


class FakeSearchClient:
    def __init__(self):
        self.pages = {
            1: {"data": [{"id": "A1", "username": "MarcioNPTV", "name": "Marcio"},
                         {"id": "A2", "username": "zz_test", "name": "Teste"}],
                "meta": {"last_page": 2}},
            2: {"data": [{"id": "A3", "username": "alice", "name": "Alice"}],
                "meta": {"last_page": 2}},
        }

    def customers(self, page, per_page=100):
        return self.pages[page]


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    import core.sigma.scraper as scraper
    monkeypatch.setattr(scraper, "init_db", database.init_db)
    monkeypatch.setattr(scraper, "save_entities", database.save_entities)
    monkeypatch.setattr(scraper, "save_raw", database.save_raw)
    database.init_db()


def test_sync_servers_packages_grava_catalogo():
    res = sync_servers_packages(FakeCatalogClient())
    assert res["servers"] == 2 and res["packages"] == 3
    assert res["synced"] == 4  # 2 servers + 2 packages (row sem id pulado)
    assert database.count_entities("server") == 2
    assert database.count_entities("package") == 2
    pkg = [p for p in list_entities("package") if p["id"] == "pkg1"][0]
    assert pkg["server_id"] == "srv1"  # o par que valida o create


def test_sync_servers_packages_aceita_envelope_laravel():
    """O painel real embrulha o catálogo em {"data": [...]} (achado na VPS)."""
    res = sync_servers_packages(FakeLaravelCatalogClient())
    assert res["servers"] == 1 and res["packages"] == 1
    assert res["synced"] == 2
    assert database.count_entities("server") == 1
    assert database.count_entities("package") == 1


def test_search_entities_escapa_like():
    database.save_entities("customer", [
        ("A1", {"username": "cem", "name": "100% Real"}),
        ("A2", {"username": "normal_user", "name": "Sem percentual"}),
    ])
    hits = search_entities("customer", "100%")
    assert len(hits) == 1 and hits[0]["id"] == "A1"  # % é literal, não curinga
    assert search_entities("customer", "inexistente") == []


def test_list_entities_pagina():
    database.save_entities("customer", [(f"C{i}", {"n": i}) for i in range(5)])
    page1 = list_entities("customer", limit=2, offset=0)
    page2 = list_entities("customer", limit=2, offset=2)
    assert len(page1) == 2 and len(page2) == 2
    assert {p["id"] for p in page1}.isdisjoint({p["id"] for p in page2})


def test_project_customer_nao_vaza_segredos():
    row = {"id": "A1", "username": "marcio", "status": "ACTIVE",
           "password": "secreta", "m3u_url": "http://x/y?password=secreta",
           "renew_url": "http://x/r", "note": "ok", "expires_at": "2026-11-03T02:59:59Z"}
    out = project_customer(row)
    assert out["username"] == "marcio" and out["note"] == "ok"
    for segredo in ("password", "m3u_url", "renew_url"):
        assert segredo not in out
        assert "secreta" not in json.dumps(out)
    assert project_customer("não-dict")["raw"].startswith("não-dict")


def test_search_customers_parcial_na_api():
    hits = search_customers(FakeSearchClient(), "MARCIO")  # case-insensitive
    assert len(hits) == 1 and hits[0]["id"] == "A1"
    assert search_customers(FakeSearchClient(), "   ") == []


def test_mcp_tem_51_tools():
    import anyio
    from interfaces.mcp.server import mcp_app

    async def _count():
        return len(await mcp_app.list_tools())

    assert anyio.run(_count) == 51  # 14 sigma + 12 woodcine + 12 blackbr + 12 newmais + 1 playlist  # 14 sigma + 8+4 woodcine + 8+4 blackbr + 8+4 newmais
