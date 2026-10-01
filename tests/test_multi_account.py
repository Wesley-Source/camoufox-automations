"""Multi-conta: load_accounts, caminhos de sessão, resolução de ativa e
failover no ensure_logged_page (single-launch, relogin só na ativa)."""
import pytest
from contextlib import contextmanager
from types import SimpleNamespace

from core.sigma import auth as auth_mod

ACC = [{"username": "alpha", "password": "p1"},
       {"username": "beta", "password": "p2"}]


class FakeContext:
    def __init__(self):
        self.cookies_added = []

    def add_cookies(self, cookies):
        self.cookies_added += cookies

    def cookies(self):
        return [{"name": "cf_clearance", "value": "x"}]


class FakeLoc:
    def count(self):
        return 0


class FakePage:
    """Cobre o que _attach_api_monitor/_restore/_session_still_valid/_login_flow tocam."""

    def __init__(self, dead_tokens=()):
        self.context = FakeContext()
        self.init_scripts = []
        self.handlers = {}
        self.url = "https://lideriptv.sigma.st/#/dashboard"
        self.dead_tokens = set(dead_tokens)
        self.fills = []

    def on(self, ev, fn):
        self.handlers[ev] = fn

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def goto(self, *a, **k):
        pass

    def locator(self, sel):
        return FakeLoc()

    def wait_for_selector(self, *a, **k):
        pass

    def fill(self, sel, value):
        self.fills.append((sel, value))

    def click(self, *a, **k):
        pass

    def wait_for_function(self, *a, **k):
        pass

    def evaluate(self, script, *args):
        if "auth/me" in script:
            tok = args[0] if args else ""
            return 401 if tok in self.dead_tokens else 200
        if "getItem" in script:
            return "tok_relogin"
        if "fromEntries" in script:
            return {}
        return 200


def make_engine(page):
    launches = []

    @contextmanager
    def get_page(proxy=None):
        launches.append(proxy)
        yield page

    return get_page, launches


@pytest.fixture
def multi_env(tmp_path, monkeypatch):
    monkeypatch.setattr(auth_mod, "ACCOUNTS_FILE", str(tmp_path / "accounts.json"))
    monkeypatch.setattr(auth_mod, "LAST_GOOD_FILE", str(tmp_path / "last_good"))
    monkeypatch.setattr(auth_mod, "SESSION_FILE", str(tmp_path / "sigma_session.json"))
    monkeypatch.setattr(auth_mod, "_VALIDATE_SETTLE", 0)
    for var in ("SIGMA_ACCOUNT", "SIGMA_USERNAME", "SIGMA_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def spath(user):
    return auth_mod.session_path_for(user, ACC)


# ---- load_accounts -------------------------------------------------------

def test_load_accounts_somente_env(multi_env, monkeypatch):
    monkeypatch.setenv("SIGMA_USERNAME", "envu")
    monkeypatch.setenv("SIGMA_PASSWORD", "envp")
    assert auth_mod.load_accounts() == [{"username": "envu", "password": "envp"}]


def test_load_accounts_arquivo_puro(multi_env):
    import json
    with open(auth_mod.ACCOUNTS_FILE, "w") as f:
        json.dump(ACC, f)
    assert auth_mod.load_accounts() == ACC


def test_load_accounts_merge_env_primeiro_sem_duplicar(multi_env, monkeypatch):
    import json
    with open(auth_mod.ACCOUNTS_FILE, "w") as f:
        json.dump([{"username": "beta", "password": "p2"},
                   {"username": "alpha", "password": "p1"}], f)
    monkeypatch.setenv("SIGMA_USERNAME", "alpha")
    monkeypatch.setenv("SIGMA_PASSWORD", "p1")
    accs = auth_mod.load_accounts()
    # env já está no arquivo: não duplica, ordem do arquivo preservada
    assert [a["username"] for a in accs] == ["beta", "alpha"]


def test_load_accounts_arquivo_invalido_vira_env(multi_env, monkeypatch):
    with open(auth_mod.ACCOUNTS_FILE, "w") as f:
        f.write("nao sou json{{{")
    monkeypatch.setenv("SIGMA_USERNAME", "envu")
    monkeypatch.setenv("SIGMA_PASSWORD", "envp")
    assert auth_mod.load_accounts() == [{"username": "envu", "password": "envp"}]


def test_load_accounts_sem_nada_vazio(multi_env):
    assert auth_mod.load_accounts() == []


# ---- session_path_for ----------------------------------------------------

def test_session_path_for_caminhos(multi_env):
    assert auth_mod.session_path_for(None) == auth_mod.SESSION_FILE
    assert spath("alpha") == auth_mod.SESSION_FILE  # primária: zero migração
    assert spath("beta").endswith(".sigma_session_beta.json")


# ---- resolve_active_account ----------------------------------------------

def test_resolve_prioridade(multi_env, monkeypatch):
    assert auth_mod.resolve_active_account(ACC)["username"] == "alpha"
    auth_mod.set_last_good("beta")
    assert auth_mod.resolve_active_account(ACC)["username"] == "beta"
    monkeypatch.setenv("SIGMA_ACCOUNT", "alpha")
    assert auth_mod.resolve_active_account(ACC)["username"] == "alpha"
    monkeypatch.setenv("SIGMA_ACCOUNT", "fantasma")  # não existe: pula
    assert auth_mod.resolve_active_account(ACC)["username"] == "beta"
    assert auth_mod.resolve_active_account([]) is None  # legado


# ---- ensure_logged_page multi ---------------------------------------------

def test_multi_reusa_primeira_candidata(multi_env, monkeypatch):
    page = FakePage()
    get_page, launches = make_engine(page)
    monkeypatch.setattr(auth_mod, "BrowserEngine", SimpleNamespace(get_page=get_page))
    monkeypatch.setattr(auth_mod, "load_accounts", lambda: ACC)
    auth_mod.save_session({"token": "tok_alpha", "cookies": [{"name": "cf"}]},
                          spath("alpha"), username="alpha")

    with auth_mod.ensure_logged_page() as s:
        assert s.reused is True
        assert s.account == "alpha"
        assert s.session_path == spath("alpha")

    assert len(launches) == 1  # CR-03: browser único
    assert auth_mod._read_last_good() == "alpha"


def test_multi_sessao_morta_cai_na_segunda(multi_env, monkeypatch):
    page = FakePage(dead_tokens={"tok_alpha"})
    get_page, launches = make_engine(page)
    monkeypatch.setattr(auth_mod, "BrowserEngine", SimpleNamespace(get_page=get_page))
    monkeypatch.setattr(auth_mod, "load_accounts", lambda: ACC)
    auth_mod.save_session({"token": "tok_alpha", "cookies": []}, spath("alpha"))
    auth_mod.save_session({"token": "tok_beta", "cookies": [{"name": "cf"}]}, spath("beta"))

    with auth_mod.ensure_logged_page() as s:
        assert s.reused is True
        assert s.account == "beta"

    assert len(launches) == 1
    assert auth_mod._read_last_good() == "beta"


def test_multi_todas_mortas_reloga_na_ativa(multi_env, monkeypatch):
    page = FakePage(dead_tokens={"tok_alpha", "tok_beta"})
    get_page, launches = make_engine(page)
    monkeypatch.setattr(auth_mod, "BrowserEngine", SimpleNamespace(get_page=get_page))
    monkeypatch.setattr(auth_mod, "load_accounts", lambda: ACC)
    auth_mod.save_session({"token": "tok_alpha", "cookies": []}, spath("alpha"))
    auth_mod.save_session({"token": "tok_beta", "cookies": [{"name": "cf"}]}, spath("beta"))

    with auth_mod.ensure_logged_page() as s:
        assert s.reused is False
        assert s.account == "alpha"  # relogin SÓ na ativa, sem cascata
        assert s.token == "tok_relogin"

    sess = auth_mod.load_session(spath("alpha"))
    assert sess["username"] == "alpha"  # regravada com dono
    assert auth_mod._read_last_good() == "alpha"


def test_multi_env_sigma_account_escolhe_sem_tocar_ponteiro(multi_env, monkeypatch):
    page = FakePage()
    get_page, _ = make_engine(page)
    monkeypatch.setattr(auth_mod, "BrowserEngine", SimpleNamespace(get_page=get_page))
    monkeypatch.setattr(auth_mod, "load_accounts", lambda: ACC)
    auth_mod.save_session({"token": "tok_beta", "cookies": [{"name": "cf"}]}, spath("beta"))
    monkeypatch.setenv("SIGMA_ACCOUNT", "beta")

    with auth_mod.ensure_logged_page() as s:
        assert s.account == "beta"
    # env NÃO grava ponteiro (é override por processo)
    assert auth_mod._read_last_good() is None
