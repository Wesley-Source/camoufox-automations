"""Paridade dos auth.py — os 3 sites devem expor a MESMA superfície.

Drift entre os gêmeos foi a causa do bug do proxy (post-mortem Hermes
02/10/2026). Este teste falha se um site perder (ou ganhar sozinho) um nome
do contrato comum, ou se a config do site dessincronizar da base
core/panel_auth.py. Correção vai no BASE, não nas cópias (AGENTS.md G5).
"""
import importlib

import pytest

SITES = {
    "core.sigma.auth": {
        "prefix": "SIGMA",
        "files": ("SESSION_FILE", "ACCOUNTS_FILE", "LAST_GOOD_FILE"),
        "url": "https://lideriptv.sigma.st",
        "monitor_scope": "/api",
    },
    "core.woodcine.auth": {
        "prefix": "WOODCINE",
        "files": ("WOODCINE_SESSION_FILE", "WOODCINE_ACCOUNTS_FILE", "WOODCINE_LAST_GOOD_FILE"),
        "url": "https://woodcine.sigma.st",
        "monitor_scope": "/api",
    },
    "core.blackbr.auth": {
        "prefix": "BLACKBR",
        "files": ("BLACKBR_SESSION_FILE", "BLACKBR_ACCOUNTS_FILE", "BLACKBR_LAST_GOOD_FILE"),
        "url": "https://painelblackbr.com",
        "monitor_scope": "host",
    },
}

# Contrato comum: tudo que consumers (cli/mcp/api/testes) importam dos auth.py.
COMMON = [
    "_attach_api_monitor",
    "_CFG",
    "_ensure_multi",
    "_login_flow",
    "_read_last_good",
    "_restore_session",
    "_session_still_valid",
    "allow_destructive",
    "default_proxy",
    "ensure_logged_page",
    "load_accounts",
    "load_session",
    "logged_page",
    "login",
    "resolve_active_account",
    "save_session",
    "session_path_for",
    "set_last_good",
]


@pytest.mark.parametrize("modname", sorted(SITES))
def test_superficie_publica_paritaria(modname):
    spec = SITES[modname]
    mod = importlib.import_module(modname)

    for name in COMMON:
        assert hasattr(mod, name), f"{modname} perdeu {name!r} do contrato comum"

    # Constantes por site presentes e coerentes com a config da base.
    url = getattr(mod, f"{spec['prefix']}_URL")
    assert url == spec["url"], f"{modname}: URL mudou sem atualizar o teste de paridade"
    assert getattr(mod, f"{spec['prefix']}_API") == f"{url}/api"
    for f in spec["files"]:
        assert hasattr(mod, f), f"{modname} perdeu a constante {f!r}"

    # _CFG ligado ao módulo certo (late binding = monkeypatch dos testes funciona).
    cfg = mod._CFG
    assert cfg.name == spec["prefix"].lower()
    assert cfg.module is mod
    assert cfg.monitor_scope == spec["monitor_scope"]
    assert str(cfg.session_file).endswith(f"{cfg.name}_session.json")


API_SITES = (
    ("sigma", "core.sigma.api", "SIGMA", "SESSION_FILE"),
    ("woodcine", "core.woodcine.api", "WOODCINE", "WOODCINE_SESSION_FILE"),
    ("blackbr", "core.blackbr.api", "BLACKBR", "BLACKBR_SESSION_FILE"),
)


@pytest.mark.parametrize("name,mod_name,prefix,session_attr", API_SITES)
def test_superficie_api_paritaria(name, mod_name, prefix, session_attr):
    """Paridade da camada API (base: core/panel_api.py)."""
    mod = importlib.import_module(mod_name)
    url = getattr(mod, f"{prefix}_URL")
    client_cls = getattr(mod, f"{prefix.capitalize()}ApiClient")

    assert client_cls.API_BASE == f"{url}/api"
    assert client_cls.HOST == url.replace("https://", "")
    assert client_cls.VENDOR == name
    assert client_cls.DEFAULT_SESSION_FILE == getattr(mod, session_attr)
    assert client_cls.API_ERROR.__name__ == f"{prefix.capitalize()}ApiError"
    # fix vendor blackbr: update não pode reenviar username/password (422 provado)
    assert client_cls.UPDATE_STRIP_FIELDS is (name == "blackbr")
    # late binding: _AUTH é o módulo do site (monkeypatch dos testes funciona)
    assert client_cls._AUTH is mod

    err = client_cls.API_ERROR("/x", 500, "boom")
    assert "boom" in str(err) and name in str(err).lower()


# ---- Paridade dos scrapers (Fase 3: core/panel_scraper.py é a base) ---------

SCRAPER_SITES = (
    ("sigma", "core.sigma.scraper", "SIGMA_API", ""),
    ("woodcine", "core.woodcine.scraper", "WOODCINE_API", "woodcine."),
    ("blackbr", "core.blackbr.scraper", "BLACKBR_API", "blackbr."),
)

SCRAPER_COMMON = (
    "CHARTS", "SYNCERS", "entities_summary", "init_db", "save_entities",
    "save_raw", "count_entities", "sync_all", "sync_customers", "sync_dashboard",
    "sync_expiring", "sync_resellers", "sync_servers_packages", "sync_statistics",
    "_CFG",
)

SYNCER_NAMES = {"customers", "expiring", "dashboard", "resellers",
                "statistics", "servers_packages"}


@pytest.mark.parametrize("name,mod_path,api_attr,kinds_prefix", SCRAPER_SITES)
def test_superficie_scraper_paritaria(name, mod_path, api_attr, kinds_prefix):
    """A superfície pública dos 3 scrapers tem que ser idêntica — drift vira
    erro de CI (AGENTS.md G5: correção vai no BASE, core/panel_scraper.py)."""
    import importlib

    mod = importlib.import_module(mod_path)
    for attr in SCRAPER_COMMON:
        assert hasattr(mod, attr), f"{mod_path} sem {attr}"
    assert set(mod.SYNCERS) == SYNCER_NAMES
    cfg = mod._CFG
    assert cfg.name == name and cfg.module is mod
    assert cfg.kinds_prefix == kinds_prefix
    assert cfg.api == getattr(mod, api_attr)
    assert mod.CHARTS == mod._base.CHARTS
