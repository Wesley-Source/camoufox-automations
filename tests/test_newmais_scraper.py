"""Scraper newmais — kinds prefixados newmais.* na panel_entities compartilhada."""
import json

import pytest

import core.database as database
import core.newmais.scraper as wc


class FakeClient:
    def __init__(self):
        self.customers_pages = 0

    def customers(self, page=1, per_page=100):
        self.customers_pages += 1
        rows = [{"id": f"w{i}", "username": f"u{page}_{i}"} for i in range(3)]
        last = {"data": rows, "meta": {"last_page": 2 if page == 1 else page}}
        return last

    def customers_expiring(self):
        return {"data": [{"id": "wx", "username": "vence"}]}

    def dashboard_chart(self, name):
        return {"labels": ["a"], "values": [1]}

    def dashboard_recovery(self):
        return {"recovered": 2}

    def resellers(self):
        return [{"id": "r1", "username": "rev"}]

    def customers_statistics(self):
        return {"data": {"mine": 10, "tree": 20}}

    def servers(self):
        return {"data": [{"id": "srv", "name": "s"}]}

    def packages(self):
        return {"data": [{"id": "pkg", "name": "p", "server_id": "srv"}]}


@pytest.fixture()
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "newmais_test.db"))
    database.init_db()
    return tmp_path


def test_sync_customers_kinds_prefixados(tmp_db, monkeypatch):
    saved = {}

    def fake_save(kind, pairs):
        pairs = list(pairs)
        saved[kind] = len(pairs)
        return len(pairs)

    monkeypatch.setattr(wc, "save_entities", fake_save)
    monkeypatch.setattr(wc, "save_raw", lambda url, raw: None)
    res = wc.sync_customers(FakeClient(), pages=1)
    assert "newmais.customer" in saved
    assert res["synced"] == 3 and res["pages"] == 1


def test_todos_os_syncs_usam_prefixo_newmais(tmp_db, monkeypatch):
    calls = []
    monkeypatch.setattr(wc, "save_entities", lambda k, pairs: calls.append(k) or len(list(pairs)))
    monkeypatch.setattr(wc, "save_raw", lambda url, raw: None)
    c = FakeClient()
    wc.sync_expiring(c)
    wc.sync_dashboard(c)
    wc.sync_resellers(c)
    wc.sync_statistics(c)
    wc.sync_servers_packages(c)
    assert calls and all(k.startswith("newmais.") for k in calls)
    assert set(calls) == {
        "newmais.expiring", "newmais.dashboard_chart", "newmais.dashboard_metric",
        "newmais.reseller", "newmais.customer_stats", "newmais.server", "newmais.package",
    }


def test_sync_all_seis_resultados(tmp_db, monkeypatch):
    monkeypatch.setattr(wc, "save_entities", lambda k, pairs: len(list(pairs)))
    monkeypatch.setattr(wc, "save_raw", lambda url, raw: None)
    res = wc.sync_all(FakeClient(), pages=1)
    assert len(res) == 6
    assert all(r["status"] == "synced" for r in res)


def test_payload_valido_e_upsert_sem_duplicar(tmp_db, monkeypatch):
    monkeypatch.setattr(wc, "save_raw", lambda url, raw: None)
    c = FakeClient()
    wc.sync_customers(c, pages=1)
    wc.sync_customers(c, pages=1)  # re-sync: UPSERT não duplica
    assert database.count_entities("newmais.customer") == 3  # mesmos 3 ids re-upsertados


def test_entities_summary_mostra_ambos_sites(tmp_db, monkeypatch):
    monkeypatch.setattr(wc, "save_raw", lambda url, raw: None)
    wc.sync_resellers(FakeClient())
    from core.database import save_entity
    save_entity("customer", "lider1", {"username": "lider"})
    s = wc.entities_summary()
    assert s["newmais.reseller"] == 1
    # coexistem no mesmo banco: kind do lider visível via count direto
    assert database.count_entities("customer") == 1
