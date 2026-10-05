"""Testes do core.http_retry — offline, sem rede (respostas fake + sleep capturado)."""
import pytest
import requests.exceptions

from core.http_retry import (
    CloudflareBlocked,
    backoff_delay,
    retry_call,
)


class R:
    def __init__(self, status_code):
        self.status_code = status_code
        self.url = "https://exemplo/api/x"


def test_sucesso_na_primeira_tentativa():
    chamadas = []
    resp = retry_call(lambda: chamadas.append(1) or R(200), sleep=lambda s: None)
    assert resp.status_code == 200
    assert len(chamadas) == 1


def test_5xx_retenta_e_consegue():
    seq = iter([R(503), R(500), R(200)])
    sleeps: list[float] = []
    resp = retry_call(lambda: next(seq), sleep=sleeps.append)
    assert resp.status_code == 200
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]  # backoff exponencial cresce


def test_5xx_esgota_e_devolve_ultima_resposta():
    resp = retry_call(lambda: R(502), attempts=3, sleep=lambda s: None)
    assert resp.status_code == 502  # caller valida — mesmo contrato de antes


def test_403_cloudflare_falha_rapida_sem_retry():
    chamadas = []

    def fn():
        chamadas.append(1)
        return R(403)

    with pytest.raises(CloudflareBlocked) as e:
        retry_call(fn, attempts=5, sleep=lambda s: None)
    assert e.value.status == 403
    assert len(chamadas) == 1  # NUNCA insistir contra o Cloudflare


def test_429_rate_limit_falha_rapida_sem_retry():
    with pytest.raises(CloudflareBlocked):
        retry_call(lambda: R(429), attempts=5, sleep=lambda s: None)


def test_erro_de_rede_retenta_e_levanta_na_ultima():
    tentativas = {"n": 0}

    def fn():
        tentativas["n"] += 1
        raise requests.exceptions.ConnectionError("boom")

    with pytest.raises(requests.exceptions.ConnectionError):
        retry_call(fn, attempts=3, sleep=lambda s: None)
    assert tentativas["n"] == 3


def test_erro_de_rede_recupera_na_segunda():
    estado = {"falhou": False}

    def fn():
        if not estado["falhou"]:
            estado["falhou"] = True
            raise requests.exceptions.Timeout("lento")
        return R(200)

    resp = retry_call(fn, sleep=lambda s: None)
    assert resp.status_code == 200


def test_dns_nunca_re_tenta():
    tentativas = {"n": 0}

    def fn():
        tentativas["n"] += 1
        raise requests.exceptions.ConnectionError(
            "Temporary failure in name resolution")

    with pytest.raises(requests.exceptions.ConnectionError):
        retry_call(fn, attempts=5, sleep=lambda s: None)
    assert tentativas["n"] == 1  # DNS é persistente: retry não ajuda


def test_on_cf_return_devolve_resposta_sem_retry():
    chamadas = []
    resp = retry_call(lambda: chamadas.append(1) or R(403),
                      attempts=5, on_cf="return", sleep=lambda s: None)
    assert resp.status_code == 403
    assert len(chamadas) == 1


def test_on_cf_invalido():
    with pytest.raises(ValueError, match="on_cf"):
        retry_call(lambda: R(200), on_cf="exploin")


def test_erro_nao_transitorio_propaga_sem_retry():
    chamadas = []

    def fn():
        chamadas.append(1)
        raise ValueError("bug de código")

    with pytest.raises(ValueError):
        retry_call(fn, sleep=lambda s: None)
    assert len(chamadas) == 1


def test_attempts_invalido():
    with pytest.raises(ValueError):
        retry_call(lambda: R(200), attempts=0)


def test_backoff_delay_cap_e_jitter():
    assert backoff_delay(0, 0.5, 8.0) < 0.7
    assert backoff_delay(10, 0.5, 8.0) <= 8.0 * 1.25  # cap + jitter
    assert backoff_delay(10, 0.5, 8.0) >= 8.0 * 0.75


# ---- integração: PanelApiClient (GET re-tenta; CF falha rápido) ------------

from core.panel_api import PanelApiError, PanelApiClient


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("sem json")
        return self._payload


class FakeSession:
    def __init__(self, resps):
        self.resps = iter(resps)
        self.calls = 0
        self.headers = {}

    def get(self, *a, **kw):
        self.calls += 1
        return next(self.resps)


class ClientFake(PanelApiClient):
    API_BASE = "https://fake.test/api"
    VENDOR = "fake"
    _AUTH = None

    def __init__(self, session):  # bypass de token/auth — só transporte
        self.token = "t"
        self._browser = False
        self._doh_ip = None
        self._doh_ts = 0.0
        self._session = session


def test_client_get_retenta_5xx_e_passa():
    sess = FakeSession([FakeResp(503), FakeResp(200, {"ok": 1})])
    c = ClientFake(sess)
    assert c._get("/x") == {"ok": 1}
    assert sess.calls == 2


def test_client_get_403_sem_retry_vira_api_error():
    # contrato do painel: 403 NÃO tem retry e NÃO vira CloudflareBlocked —
    # volta como API_ERROR (fallback browser decide o caminho, não o retry)
    sess = FakeSession([FakeResp(403)])
    c = ClientFake(sess)
    with pytest.raises(PanelApiError) as e:
        c._get("/x")
    assert e.value.status == 403
    assert sess.calls == 1  # CF: falha rápida, sem segunda tentativa


def test_client_erro_rede_propaga_na_primeira():
    # contrato do painel: offline/timeout NÃO re-tenta (fallback é browser)
    estado = {"n": 0}

    class Sess:
        headers = {}

        def get(self, *a, **kw):
            estado["n"] += 1
            raise requests.exceptions.ConnectionError("connection refused")

    c = ClientFake(Sess())
    with pytest.raises(requests.exceptions.ConnectionError):
        c._get("/x")
    assert estado["n"] == 1


def test_client_dns_propaga_na_primeira():
    estado = {"n": 0}

    class Sess:
        headers = {}

        def get(self, *a, **kw):
            estado["n"] += 1
            raise requests.exceptions.ConnectionError(
                "Temporary failure in name resolution")

    c = ClientFake(Sess())
    with pytest.raises(requests.exceptions.ConnectionError):
        c._get("/x")
    assert estado["n"] == 1


def test_client_get_5xx_esgotado_vira_api_error():
    sess = FakeSession([FakeResp(500, text="x"), FakeResp(500, text="x")])
    c = ClientFake(sess)
    c.RETRY_ATTEMPTS = 2  # instância: encurta o teste (1 sleep real)
    with pytest.raises(PanelApiError) as e:
        c._get("/x")
    assert e.value.status == 500
    assert sess.calls == 2
