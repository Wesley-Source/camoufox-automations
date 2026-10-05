"""Testes do browser e do proxy (CR-02: Camoufox quer dict, não str).

O teste de default_proxy (usa core.<site>.auth do repo privado) vive no
privado, anexado a tests/test_sigma_auth.py.
"""
from core.browser import _normalize_proxy


def test_normalize_proxy_str_vira_dict():
    assert _normalize_proxy("socks5://100.1.2.3:1080") == {
        "server": "socks5://100.1.2.3:1080"
    }


def test_normalize_proxy_dict_e_none_passam_direto():
    d = {"server": "http://p:1", "username": "u", "password": "s"}
    assert _normalize_proxy(d) is d
    assert _normalize_proxy(None) is None
