"""Onda 4: o motor de PRODUÇÃO (_BrowserTransport) finalmente coberto.

Até hoje os testes só exercitavam o motor requests (bloqueado pelo CF em
produção). Aqui simulamos a page.evaluate do Playwright e validamos que o
client monta URL/headers/body certos e propaga timeout.
"""
import json

import pytest

from core.sigma.api import SigmaApiClient, SigmaApiError, _BrowserTransport


class FakePage:
    """page.evaluate falso: grava os argumentos e devolve resposta enlatada."""

    def __init__(self, result=None, fail=False):
        self.calls = []
        self.result = result or [200, '{"ok": true}']
        self.fail = fail  # se True, evaluate levanta (erro real do browser)

    def evaluate(self, js, args):
        if self.fail:
            raise RuntimeError("boom no browser")
        self.calls.append(args)
        return list(self.result)


def make_client(page):
    return SigmaApiClient(token="tok123", transport=_BrowserTransport(page))


def test_get_monta_url_headers_e_timeout():
    page = FakePage()
    client = make_client(page)
    transport = client._session
    transport._extra = {"Accept": "application/json"}
    r = transport.get("https://x/api/customers", params={"page": 2, "perPage": 100},
                      headers={"Authorization": "Bearer tok123"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    url, headers, method, body, timeout = page.calls[0]
    assert url == "https://x/api/customers?page=2&perPage=100"
    assert headers == {"Accept": "application/json", "Authorization": "Bearer tok123"}
    assert method == "GET"
    assert body is None
    assert timeout == 30_000


def test_request_serializa_json_e_metodo_maiusculo():
    page = FakePage(result=[201, '{"data": {"id": "abc"}}'])
    client = make_client(page)
    r = client._session.request(
        "post", "https://x/api/customers", json={"username": "zz"},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201
    url, headers, method, body, timeout = page.calls[0]
    assert method == "POST"
    assert json.loads(body) == {"username": "zz"}
    assert headers["Content-Type"] == "application/json"


def test_timeout_vira_TimeoutError():
    page = FakePage(result=["TIMEOUT", ""])
    client = make_client(page)
    with pytest.raises(TimeoutError):
        client._session.get("https://x/api/slow")
    with pytest.raises(TimeoutError):
        client._session.request("POST", "https://x/api/slow", json={})


def test_cliente_get_end_to_end_via_browser():
    """_get completo: payload Laravel parseado a partir do transporte real."""
    payload = {"data": [{"id": "a1", "username": "u"}], "meta": {"last_page": 3}}
    page = FakePage(result=[200, json.dumps(payload)])
    client = make_client(page)
    data = client.customers(page=1)
    assert data["meta"]["last_page"] == 3
    url = page.calls[0][0]
    assert "perPage=100" in url and "Authorization" in page.calls[0][1]


def test_cliente_erro_levanta_SigmaApiError():
    page = FakePage(result=[500, "server boomed"])
    client = make_client(page)
    with pytest.raises(SigmaApiError) as e:
        client.me()
    assert e.value.status == 500


def test_cliente_mutate_passa_headers_axios():
    """Sem Accept/X-Requested-With o Laravel responde validação com 302→HTML
    (descoberta do 07) — o client TEM que mandar os headers."""
    page = FakePage(result=[201, '{"data": {"id": "n1"}}'])
    client = make_client(page)
    client.create_customer({"username": "zz_test"})
    _, headers, method, body, _ = page.calls[0]
    assert method == "POST"
    assert headers["Accept"] == "application/json"
    assert headers["X-Requested-With"] == "XMLHttpRequest"
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer tok123"
    assert json.loads(body) == {"username": "zz_test"}


def test_browser_erro_real_propaga():
    client = make_client(FakePage(fail=True))
    with pytest.raises(RuntimeError, match="boom"):
        client.me()
