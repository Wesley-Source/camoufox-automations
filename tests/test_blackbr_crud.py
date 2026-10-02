"""CRUD blackbr — métodos mutantes com headers axios e erros honestos (offline)."""
import json

import pytest

import core.blackbr.api as wapi
from core.blackbr.api import BlackbrApiClient as WC


def test_alias_classe_e_blackbr():
    # o port cp+sed manteve o nome BlackbrApiClient dentro do módulo blackbr
    assert hasattr(wapi, "BlackbrApiClient")
    assert wapi.BLACKBR_API == "https://painelblackbr.com/api"


class FakeResponse:
    def __init__(self, status_code=200, text="{}"):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self.responses.pop(0)

    def mount(self, prefix, adapter):
        pass


def make_client(responses):
    c = wapi.BlackbrApiClient.__new__(wapi.BlackbrApiClient)
    c.token = "tok"
    c.session_path = "blackbr_session.json"
    c._doh_ip = None
    c._doh_ts = 0.0
    c._browser = False
    c._session = FakeSession(responses)
    return c


def test_create_manda_axios_headers_e_payload():
    c = make_client([FakeResponse(201, '{"data": {"id": "abc"}}')])
    res = c.create_customer({"username": "u1", "password": "p", "password_confirmation": "p"})
    call = c._session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://painelblackbr.com/api/customers"
    h = call["headers"]
    assert h["Accept"] == "application/json"
    assert h["X-Requested-With"] == "XMLHttpRequest"
    assert h["Content-Type"] == "application/json"
    assert h["Authorization"] == "Bearer tok"
    assert call["json"]["username"] == "u1"
    assert res["data"]["id"] == "abc"


def test_update_resync_delete_urls_e_metodos():
    c = make_client([FakeResponse(200, "{}"), FakeResponse(200, "{}"), FakeResponse(200, '{"deleted_at": "x"}')])
    c.update_customer("ID1", {"note": "n"})
    c.resync_customer("ID1")
    c.delete_customer("ID1")
    methods = [(x["method"], x["url"]) for x in c._session.calls]
    assert methods == [
        ("PUT", "https://painelblackbr.com/api/customers/ID1"),
        ("POST", "https://painelblackbr.com/api/customers/ID1/resync"),
        ("DELETE", "https://painelblackbr.com/api/customers/ID1"),
    ]


def test_422_vira_blackbr_error():
    c = make_client([FakeResponse(422, '{"message": "The given data was invalid.", "errors": {"username": ["required"]}}')])
    with pytest.raises(wapi.BlackbrApiError) as e:
        c.create_customer({"username": "!!!"})
    assert "422" in str(e.value) and "username" in str(e.value)


def test_nao_json_200_vira_error():
    c = make_client([FakeResponse(200, "<html>cf challenge</html>")])
    with pytest.raises(wapi.BlackbrApiError, match="JSON"):
        c.delete_customer("ID1")


def test_project_customer_nunca_vaza_segredos():
    row = {"id": "x", "username": "u", "status": "ACTIVE", "password": "SENHA",
           "m3u_url": "http://x/y?pwd=1", "renew_url": "http://r"}
    out = wapi.project_customer(row)
    assert out["username"] == "u"
    assert "password" not in out and "m3u_url" not in out and "renew_url" not in out
