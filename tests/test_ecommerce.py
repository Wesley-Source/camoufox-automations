import json

import core.ecommerce_x.scraper as ecom
from core.database import init_db
from core.ecommerce_x.scraper import sync_product


class _FakePage:
    def goto(self, *a, **kw):
        pass

    def evaluate(self, *_):
        return {"slideshow": {"title": "fake"}}


class _FakeEngine:
    @staticmethod
    def get_page(*a, **kw):
        import contextlib

        @contextlib.contextmanager
        def _cm():
            yield _FakePage()

        return _cm()


def test_sync_product_retorna_estrutura_esperada(monkeypatch, tmp_path):
    # offline: sem browser real (Xvfb/rede) nem DB do repo
    monkeypatch.setattr(ecom, "BrowserEngine", _FakeEngine)
    monkeypatch.setattr("core.database.DB_PATH", str(tmp_path / "t.db"))
    init_db()

    res = sync_product("TEST_1")

    assert res["id"] == "TEST_1"
    assert res["status"] == "synced"
    assert isinstance(res["price"], float)
    assert isinstance(res["title"], str)
