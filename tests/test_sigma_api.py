"""Testes do SigmaApiClient — tudo offline (session fake + monkeypatch)."""
import pytest

from core.sigma import api as sigma_api
from core.sigma.api import (
    SigmaApiClient,
    SigmaApiError,
    customer_new_expiry,
    doh_resolve,
    _is_dns_failure,
)


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


# ---- CR-04: roundtrip de expiração sem dia fantasma cumulativo -------------

def test_renovacao_expires_at_avanca_exatos_30_dias():
    # 04/11 02:59:59Z = 03/11 23:59:59 local (UTC-3) -> +30 = 03/12 local
    row = {"expires_at": "2026-11-04T02:59:59.000000Z"}
    assert customer_new_expiry(row, add_days=30) == "2026-12-03"


def test_renovacao_dupla_nao_acumula_dia_fantasma():
    # set_expiry_on_payload grava (ymd+1)T02:59:59Z; reler e renovar de novo
    # deve avançar exatamente +30 outra vez, não +31.
    row = {"expires_at": "2026-11-04T02:59:59.000000Z"}
    ymd1 = customer_new_expiry(row, add_days=30)            # 2026-12-03
    row2 = {"expires_at": "2026-12-04T02:59:59.000000Z"}    # o que seria gravado
    assert ymd1 == "2026-12-03"
    assert customer_new_expiry(row2, add_days=30) == "2027-01-02"


def test_expiry_date_e_due_date_nao_sofrem_ajuste():
    assert customer_new_expiry({"expiry_date": "2026-11-03"}, 1) == "2026-11-04"
    assert customer_new_expiry({"due_date": "2026-11-03"}, 2) == "2026-11-05"


def test_precedencia_canonica_expires_at_primeiro():  # A4
    # datas divergentes: o canônico expires_at vence a expiry_date velha
    row = {"expiry_date": "2026-01-01", "expires_at": "2026-12-04T02:59:59.000000Z"}
    assert customer_new_expiry(row, add_days=0) == "2026-12-03"


def test_id_vai_urlencoded_na_url(client):  # CR-13: path injection
    client._session.responses = [FakeResponse(200, "{}")]
    client.delete_customer("a/b?c")
    url = client._session.calls[-1]["url"]
    assert "/customers/a%2Fb%3Fc" in url


def test_mutate_aceita_204(client):  # CR-22
    client._session.responses = [FakeResponse(204, text="")]
    assert client.resync_customer("abc1") == {}


def test_doh_pin_expira(monkeypatch):  # CR-21
    c = sigma_api.SigmaApiClient.__new__(sigma_api.SigmaApiClient)
    c._browser = False
    c._doh_ip = "1.2.3.4"
    c._doh_ts = sigma_api.time.monotonic() - sigma_api._DOH_TTL - 1
    assert sigma_api.time.monotonic() - c._doh_ts >= sigma_api._DOH_TTL


def test_mcp_login_sigma_mascara_token(monkeypatch):  # B2
    import interfaces.mcp.sigma as m
    monkeypatch.setenv("SIGMA_USERNAME", "u")
    monkeypatch.setenv("SIGMA_PASSWORD", "p")
    monkeypatch.setattr(m, "login", lambda u, p: {"token": "6925|ABCDEFGHJKLMNOPQRS1234"})
    out = m._login_sigma()
    assert "6925|ABCDEFGHJKL" in out          # prefixo de 16 chars visível
    assert "PQRS1234" not in out             # cauda fora do transcript


def test_project_response_nao_vaza_row():  # M2
    from core.sigma.api import project_response
    row = {"id": "X1", "deleted_at": "2026-10-01", "status": "ok", "password": "sec"}
    out = project_response(row)
    assert out == {"id": "X1", "deleted_at": "2026-10-01", "status": "ok"}
    assert "password" not in out
    assert project_response("<html>cf</html>") == {"raw": "<html>cf</html>"}
