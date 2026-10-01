"""Testes do browser e do proxy (CR-02: Camoufox quer dict, não str)."""
from core.browser import _normalize_proxy
from core.sigma.auth import default_proxy


def test_default_proxy_do_env(monkeypatch):
    monkeypatch.delenv("SIGMA_PROXY", raising=False)
    assert default_proxy() is None
    monkeypatch.setenv("SIGMA_PROXY", "socks5://100.1.2.3:1080")
    assert default_proxy() == "socks5://100.1.2.3:1080"


def test_normalize_proxy_str_vira_dict():
    assert _normalize_proxy("socks5://100.1.2.3:1080") == {
        "server": "socks5://100.1.2.3:1080"
    }


def test_normalize_proxy_dict_e_none_passam_direto():
    d = {"server": "http://p:1", "username": "u", "password": "s"}
    assert _normalize_proxy(d) is d
    assert _normalize_proxy(None) is None
