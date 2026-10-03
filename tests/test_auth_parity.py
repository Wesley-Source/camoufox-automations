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
