"""Gaps de teste da Onda C: boot real do client, ramos CR-23/M-baixa,
set_expiry_on_payload completo, dispatch inválido (CLI/MCP/automations) e
caminhos de sessão do auth.py (_restore/_still_valid/ensure_logged_page)."""
from contextlib import contextmanager

import pytest

from core.sigma import api as sigma_api
from core.sigma import auth as auth_mod
from core.sigma.api import SigmaApiClient, customer_new_expiry, set_expiry_on_payload
from core.sigma.scraper import sync_customers


# ---- fakes -------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.cookies = type("C", (), {"set": staticmethod(lambda *a, **k: None)})()

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url})
        return self.responses.pop(0)

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "method": method})
        return self.responses.pop(0)

    def mount(self, prefix, adapter):
        pass


class FakePage:
    """Página fake p/ auth: grava chamadas e devolve respostas enlatadas."""

    def __init__(self, url="https://lideriptv.sigma.st/#/dashboard",
                 evaluates=(), locator_count=0):
        self.url = url
        self._evaluates = list(evaluates)
        self._locator_count = locator_count
        self.added_cookies = []
        self.init_scripts = []
        self.context = type("Ctx", (), {})()
        self.context.add_cookies = self.added_cookies.extend
        self.context.cookies = lambda: []

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def on(self, *a, **k):
        pass

    def goto(self, *a, **k):
        pass

    def wait_for_selector(self, *a, **k):
        pass

    def fill(self, *a, **k):
        pass

    def click(self, *a, **k):
        pass

    def wait_for_function(self, *a, **k):
        pass

    def locator(self, sel):
        return type("Loc", (), {"count": lambda s: self._locator_count})()

    def evaluate(self, expr, *args):
        return self._evaluates.pop(0)


# ---- boot real do SigmaApiClient (fixtures antigos usam __new__) -------------

def test_init_com_sessao_valida_usa_token_do_arquivo(monkeypatch):
    monkeypatch.setattr(sigma_api, "load_session",
                        lambda p: {"token": "sess|tok", "cookies": []})
    c = SigmaApiClient(transport=FakeSession([FakeResponse(200, {"ok": 1})]))
    assert c.token == "sess|tok"
    assert c._session.calls[0]["url"].endswith("/api/auth/me")


def test_init_reloga_quando_sessao_morta(monkeypatch):
    sessions = [{"token": "dead|tok", "cookies": []},
                {"token": "fresh|tok", "cookies": []}]
    monkeypatch.setattr(sigma_api, "load_session", lambda p: sessions.pop(0))

    @contextmanager
    def _fake_ensure(session_path=None, proxy=None, guard=None):
        yield __import__("types").SimpleNamespace(token="fresh|tok")
    monkeypatch.setattr(sigma_api, "ensure_logged_page", _fake_ensure)

    c = SigmaApiClient(transport=FakeSession([FakeResponse(401, text="no")]))
    assert c.token == "fresh|tok"


def test_init_sem_sessao_e_sem_ensure_propaga_erro(monkeypatch):
    monkeypatch.setattr(sigma_api, "load_session", lambda p: None)

    @staticmethod
    def _boom(*a, **k):
        raise RuntimeError("Sem sessão válida e sem credenciais.")
    monkeypatch.setattr(sigma_api, "ensure_logged_page", _boom)
    with pytest.raises(RuntimeError, match="Sem sessão"):
        SigmaApiClient(transport=FakeSession([]))


# ---- CR-23: sem meta.last_page, para em página vazia -------------------------

class PgClient:
    def __init__(self):
        self.pages = []

    def customers(self, page, per_page=100):
        self.pages.append(page)
        if page == 1:
            return {"data": [{"id": "A1", "name": "x"}]}  # sem meta
        return {"data": []}


def test_sync_customers_sem_last_page_para_em_pagina_vazia(monkeypatch):
    monkeypatch.setattr("core.sigma.scraper.init_db", lambda: None)
    monkeypatch.setattr("core.sigma.scraper.save_raw", lambda *a, **k: None)
    monkeypatch.setattr("core.sigma.scraper.save_entities", lambda k, pairs: len(pairs))
    c = PgClient()
    res = sync_customers(c, pages=10)
    assert res["pages"] == 2 and res["synced"] == 1
    assert c.pages == [1, 2]  # sem loop infinito


# ---- set_expiry_on_payload completo (3 formatos + ValueError) ----------------

def test_set_expiry_expires_at_e_canonico_e_limpa_variantes():
    p = {"expires_at": "old", "expiry_date": "velho", "due_date": "velho"}
    set_expiry_on_payload({"expires_at": "x"}, p, "2026-11-03")
    assert p["expires_at"] == "2026-11-04T02:59:59.000000Z"
    assert "expiry_date" not in p and "due_date" not in p


def test_set_expiry_expiry_date_e_due_date():
    p = {}
    set_expiry_on_payload({"expiry_date": "x"}, p, "2026-11-03")
    assert p["expiry_date"] == "2026-11-03"
    p = {"due_date": "x", "expiry_date": "velho"}
    set_expiry_on_payload({"due_date": "x"}, p, "2026-11-05")
    assert p["due_date"] == "2026-11-05"


def test_set_expiry_row_sem_campo_levanta_valueerror():
    with pytest.raises(ValueError):
        set_expiry_on_payload({}, {}, "2026-11-03")


def test_customer_new_expiry_set_date_base():
    assert customer_new_expiry({}, set_date="2026-12-01") == "2026-12-01"
    assert customer_new_expiry({"expires_at": "2026-12-04T02:59:59Z"}, add_days=3) == "2026-12-06"


# ---- dispatch inválido (CLI / MCP / automations) -----------------------------

def test_cli_sigma_sync_what_invalido_exit_1():
    from interfaces.cli import cli_app
    assert cli_app(["sigma-sync", "--what", "x"], standalone_mode=False) == 1


def test_cli_automations_status_invalido_exit_1():
    from interfaces.cli import cli_app
    assert cli_app(["automations", "--status", "x"], standalone_mode=False) == 1


def test_mcp_sincronizar_o_que_invalido_erro_em_texto():
    from interfaces.mcp import sigma as mcp_sigma
    out = mcp_sigma._sincronizar_sigma("x", 5, 100)
    assert "inválido" in out


# ---- auth: _restore_session / _session_still_valid ---------------------------

def test_restore_session_injeta_cookies_e_localstorage():
    page = FakePage()
    sess = {"cookies": [{"name": "cf", "value": "x"}],
            "local_storage": {"token": "t|1"}}
    auth_mod._restore_session(page, sess)
    assert page.added_cookies == [{"name": "cf", "value": "x"}]
    assert "t\\|1" in page.init_scripts[0] or "t|1" in page.init_scripts[0]
    assert "localStorage.setItem" in page.init_scripts[0]


def test_sessao_valida_true_e_falsos(monkeypatch):
    monkeypatch.setattr(auth_mod, "_VALIDATE_SETTLE", 0)
    ok = FakePage(evaluates=[200])
    assert auth_mod._session_still_valid(ok, [], "t|1") is True
    assert auth_mod._session_still_valid(
        FakePage(url="https://lideriptv.sigma.st/#/sign-in"), [], "t") is False
    assert auth_mod._session_still_valid(
        FakePage(locator_count=1), [], "t") is False
    capt = [{"url": "https://x/api/auth/me", "status": 401}]
    assert auth_mod._session_still_valid(FakePage(evaluates=[200]), capt, "t") is False


def test_sessao_valida_erro_de_rede_propaga(monkeypatch):
    monkeypatch.setattr(auth_mod, "_VALIDATE_SETTLE", 0)

    class Boom(FakePage):
        def goto(self, *a, **k):
            raise ConnectionError("proxy caiu")

    with pytest.raises(RuntimeError, match="rede/proxy"):
        auth_mod._session_still_valid(Boom(), [], "t")


# ---- ensure_logged_page: reused / relogin / sem creds ------------------------

def fake_engine(page):
    """Retorna (get_page, launches) — conta launches, página única (CR-03)."""
    launches = []

    def get_page(proxy=None):
        launches.append(proxy)

        @contextmanager
        def _cm():
            yield page
        return _cm()

    return get_page, launches


@pytest.fixture
def no_proxy_env(monkeypatch):
    monkeypatch.delenv("SIGMA_PROXY", raising=False)
    monkeypatch.delenv("SIGMA_USERNAME", raising=False)
    monkeypatch.delenv("SIGMA_PASSWORD", raising=False)


def test_ensure_reused_browser_unico(monkeypatch, no_proxy_env):
    monkeypatch.setattr(auth_mod, "_VALIDATE_SETTLE", 0)
    monkeypatch.setattr(auth_mod, "load_session",
                        lambda p: {"token": "t|ok", "cookies": [], "local_storage": {}})
    get_page, launches = fake_engine(FakePage(evaluates=[200]))
    monkeypatch.setattr(auth_mod, "BrowserEngine",
                        type("E", (), {"get_page": staticmethod(get_page)}))
    with auth_mod.ensure_logged_page() as s:
        assert s.reused is True and s.token == "t|ok"
    assert len(launches) == 1  # CR-03 single-launch


def test_ensure_relogin_na_mesma_pagina_salva_sessao(monkeypatch, no_proxy_env):
    monkeypatch.setattr(auth_mod, "_VALIDATE_SETTLE", 0)
    monkeypatch.setattr(auth_mod, "load_session", lambda p: None)
    monkeypatch.setenv("SIGMA_USERNAME", "u")
    monkeypatch.setenv("SIGMA_PASSWORD", "p")
    saved = []
    monkeypatch.setattr(auth_mod, "save_session", lambda s, p, username=None: saved.append(s))
    page = FakePage(evaluates=["new|tok", {}])
    get_page, launches = fake_engine(page)
    monkeypatch.setattr(auth_mod, "BrowserEngine",
                        type("E", (), {"get_page": staticmethod(get_page)}))
    with auth_mod.ensure_logged_page() as s:
        assert s.reused is False and s.token == "new|tok"
    assert len(saved) == 1 and saved[0]["token"] == "new|tok"
    assert len(launches) == 1


def test_ensure_sem_sessao_e_sem_creds_levanta(monkeypatch, no_proxy_env):
    monkeypatch.setattr(auth_mod, "_VALIDATE_SETTLE", 0)
    monkeypatch.setattr(auth_mod, "load_session", lambda p: None)
    get_page, _ = fake_engine(FakePage())
    monkeypatch.setattr(auth_mod, "BrowserEngine",
                        type("E", (), {"get_page": staticmethod(get_page)}))
    with pytest.raises(RuntimeError, match="Sem sessão válida"):
        with auth_mod.ensure_logged_page():
            pass
