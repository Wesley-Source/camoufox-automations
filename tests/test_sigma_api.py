"""Testes do SigmaApiClient — tudo offline (session fake + monkeypatch)."""
import pytest

from core.sigma import api as sigma_api
from core.sigma.api import SigmaApiClient, SigmaApiError, doh_resolve, _is_dns_failure


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
    """Substitui requests.Session gravando as chamadas."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}
        self.cookies = type("C", (), {"set": staticmethod(lambda *a, **k: None)})()

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": params,
                           "method": "GET", "json": None})
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": None,
                           "method": method, "json": json})
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def mount(self, prefix, adapter):  # no-op no fake
        pass


@pytest.fixture
def client():
    c = SigmaApiClient.__new__(SigmaApiClient)  # pula boot/validação de rede
    c.session_path = "/tmp/x.json"
    c._doh_ip = None
    c._browser = False
    c.token = "TEST|token"
    c._session = FakeSession([])
    return c


def test_auth_header_enviada(client):
    client._session.responses = [FakeResponse(200, {"ok": True})]
    client._get("/auth/me")
    assert client._session.headers["Authorization"] == "Bearer TEST|token"
    assert client._session.calls[0]["url"].endswith("/api/auth/me")


def test_nao_200_levanta_erro(client):
    client._session.responses = [FakeResponse(403, text="<html>cf-block</html>")]
    with pytest.raises(SigmaApiError) as e:
        client._get("/customers")
    assert e.value.status == 403


def test_params_de_paginacao(client):
    client._session.responses = [FakeResponse(200, {"data": []})]
    client.customers(page=3, per_page=50)
    # camelCase: a API ignora per_page snake_case (silencioso)
    assert client._session.calls[0]["params"] == {"page": 3, "perPage": 50}


def test_dns_failure_cai_no_doh(client, monkeypatch):
    dns_err = sigma_api.requests.exceptions.ConnectionError(
        "HTTPSConnectionPool: Name or service not known"
    )
    client._session.responses = [dns_err, FakeResponse(200, {"data": []})]
    monkeypatch.setattr(sigma_api, "doh_resolve", lambda host: "104.26.9.179")
    data = client._get("/customers")
    assert data == {"data": []}
    # 2ª chamada foi por IP com Host do domínio
    assert client._doh_ip == "104.26.9.179"
    assert client._session.calls[1]["url"].startswith("https://104.26.9.179/")
    assert client._session.calls[1]["headers"]["Host"] == "lideriptv.sigma.st"


def test_dns_failure_sem_doh_propaga(client, monkeypatch):
    dns_err = sigma_api.requests.exceptions.ConnectionError(
        "Temporary failure in name resolution"
    )
    client._session.responses = [dns_err]
    monkeypatch.setattr(sigma_api, "doh_resolve", lambda host: None)
    with pytest.raises(sigma_api.requests.exceptions.ConnectionError):
        client._get("/customers")


def test_erro_nao_dns_propaga(client):
    client._session.responses = [sigma_api.requests.exceptions.ConnectionError(
        "connection refused")]
    with pytest.raises(sigma_api.requests.exceptions.ConnectionError):
        client._get("/customers")


def test_doh_resolve_parse(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self):
            return {"Answer": [{"type": 1, "data": "104.26.9.179"},
                               {"type": 5, "data": "alias"}]}
    monkeypatch.setattr(sigma_api.requests, "get", lambda *a, **k: R())
    assert doh_resolve("lideriptv.sigma.st") == "104.26.9.179"


def test_doh_resolve_sem_resposta(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"Answer": []}
    monkeypatch.setattr(sigma_api.requests, "get", lambda *a, **k: R())
    assert doh_resolve("x.example") is None


def test_is_dns_failure():
    assert _is_dns_failure(Exception("Name or service not known"))
    assert _is_dns_failure(Exception("Temporary failure in name resolution"))
    assert not _is_dns_failure(Exception("connection refused"))


# ---- mutações (port do 07) ---------------------------------------------------

def test_create_customer_envia_payload_e_headers_axios(client):
    client._session.responses = [FakeResponse(201, {"data": {"id": "ABC123xYz"}})]
    payload = {"username": "zz_test", "server_id": 1, "package_id": 2}
    client.create_customer(payload)
    call = client._session.calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/api/customers")
    assert call["json"] == payload
    # sem os headers axios o Laravel responde 302→HTML 200 (parece sucesso)
    assert call["headers"]["Accept"] == "application/json"
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert call["headers"]["Content-Type"] == "application/json"
    assert call["headers"]["Authorization"] == "Bearer TEST|token"


def test_update_resync_delete_montam_url_do_id(client):
    client._session.responses = [
        FakeResponse(200, {"ok": 1}),   # PUT
        FakeResponse(200, {"ok": 1}),   # resync
        FakeResponse(200, {"deleted_at": "2026-09-30"}),  # DELETE
    ]
    client.update_customer("ABC123xYz", {"name": "novo"})
    client.resync_customer("ABC123xYz")
    client.delete_customer("ABC123xYz")
    assert client._session.calls[0]["method"] == "PUT"
    assert client._session.calls[0]["url"].endswith("/api/customers/ABC123xYz")
    assert client._session.calls[1]["method"] == "POST"
    assert client._session.calls[1]["url"].endswith("/customers/ABC123xYz/resync")
    assert client._session.calls[2]["method"] == "DELETE"


def test_mutacao_nao_2xx_levanta_erro(client):
    client._session.responses = [FakeResponse(
        422, text='{"errors": {"server_id": ["The server id field is required."]}}')]
    with pytest.raises(SigmaApiError) as e:
        client.create_customer({"username": "zz_test"})
    assert e.value.status == 422


def test_mutacao_corpo_nao_json_levanta_erro(client):
    client._session.responses = [FakeResponse(200, text="<html>spa</html>")]
    with pytest.raises(SigmaApiError, match="não-JSON"):
        client.delete_customer("ABC123xYz")
