"""Testes do sync Sigma — client fake + banco em arquivo temporário."""
import json

import pytest

import core.database as database
from core.sigma.scraper import (
    sync_all, sync_customers, sync_dashboard, sync_expiring,
    sync_resellers, sync_statistics, entities_summary,
)


class FakeClient:
    """Canned responses no formato real da API (Laravel paginator etc.)."""

    def __init__(self):
        self.customers_pages = {
            1: {"data": [{"id": f"C{i}", "username": f"user{i}"} for i in range(15)],
                "meta": {"current_page": 1, "last_page": 2, "total": 20}},
            2: {"data": [{"id": f"C{i}", "username": f"user{i}"} for i in range(15, 20)],
                "meta": {"current_page": 2, "last_page": 2, "total": 20}},
        }

    def customers(self, page, per_page=15):
        return self.customers_pages[page]

    def customers_expiring(self):
        return {"data": [{"id": "E1", "username": "soon"}]}

    def dashboard_chart(self, name):
        return {"description": name, "total": 7}

    def dashboard_recovery(self):
        return {"metric": "recovery", "value": 1.5}

    def resellers(self):
        return [{"id": "R1", "username": "rev", "parent": None}]

    def customers_statistics(self):
        return {"data": {"mine": {"a": 1}, "tree": [{"b": 2}]}}


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    # scraper lê DB_PATH via módulo database (import * não copia constantes aqui)
    import core.sigma.scraper as scraper
    monkeypatch.setattr(scraper, "init_db", database.init_db)
    monkeypatch.setattr(scraper, "save_entity", database.save_entity)
    monkeypatch.setattr(scraper, "save_raw", database.save_raw)
    monkeypatch.setattr(scraper, "count_entities", database.count_entities)
    return str(tmp_path / "test.db")


def test_sync_customers_paginacao_e_upsert():
    c = FakeClient()
    res = sync_customers(c, pages=99)  # para sozinho no last_page
    assert res == {"what": "customers", "synced": 20, "pages": 2, "status": "synced"}

    # re-sync não duplica (UPSERT)
    sync_customers(c, pages=99)
    assert database.count_entities("customer") == 20
    with database.sqlite3.connect(database.DB_PATH) as conn:
        raws = conn.execute("SELECT COUNT(*) FROM raw_snapshots").fetchone()[0]
    assert raws == 4  # 2 pages x 2 runs


def test_sync_demais_datasets():
    c = FakeClient()
    assert sync_expiring(c)["synced"] == 1
    assert sync_dashboard(c)["synced"] == 5  # 4 charts + recovery
    assert sync_resellers(c)["synced"] == 1
    assert sync_statistics(c)["synced"] == 2  # mine + tree
    summary = entities_summary()
    assert summary["expiring"] == 1
    assert summary["dashboard_chart"] == 4
    assert summary["dashboard_metric"] == 1
    assert summary["reseller"] == 1
    assert summary["customer_stats"] == 2


def test_payload_e_json_valido():
    sync_resellers(FakeClient())
    with database.sqlite3.connect(database.DB_PATH) as conn:
        payload = conn.execute(
            "SELECT payload FROM panel_entities WHERE kind='reseller'"
        ).fetchone()[0]
    assert json.loads(payload)["username"] == "rev"


def test_sync_all_roda_tudo():
    results = sync_all(FakeClient(), pages=1)
    assert len(results) == 5
    assert all(r["status"] == "synced" for r in results)
