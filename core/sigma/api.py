"""
Cliente read-only da API do painel Sigma.

Segurança por construção: só existem métodos GET, um por endpoint mapeado
em explore/PANEL_MAP.md. Nenhuma superfície de mutação.

TRANSPORTE: o Cloudflare exige fingerprint de browser (requests puro toma
403 "Just a moment"), então o caminho padrão é `open_client()`: browser via
Playwright e as chamadas passam por page.context.request (TLS real + cookies
da sessão, sem renderizar página). O motor requests+DoH permanece como
fallback/motor de teste (unit tests), mas é bloqueado pelo CF em produção.

Auth: token de sigma_session.json (auth.load_session), "Authorization:
Bearer". `ensure_logged_page` reutiliza a sessão salva ou refaz o login no
browser — validade é decisão do servidor (/api/auth/me).
"""
from contextlib import contextmanager

import requests
import typer

from core.sigma.auth import (
    SIGMA_API,
    SIGMA_URL,
    ensure_logged_page,
    load_session,
)

SIGMA_HOST = SIGMA_URL.replace("https://", "")
_DOH_URL = "https://dns.google/resolve"
_BODY_SNIPPET = 500
# UA Firefox — cf_clearance é emitido por browser; UA python-requests puro
# aumenta a chance de desafio do Cloudflare.
_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"

_DNS_ERRORS = ("name or service not known", "temporary failure in name resolution",
               "nameresolutionerror", "getaddrinfo failed")


def _is_dns_failure(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _DNS_ERRORS)


def doh_resolve(host: str) -> str | None:
    """Resolve A record via DoH do Google (dns.google resolve sempre aqui)."""
    try:
        r = requests.get(_DOH_URL, params={"name": host, "type": "A"}, timeout=10)
        r.raise_for_status()
        for answer in r.json().get("Answer", []):
            if answer.get("type") == 1:
                return answer["data"]
    except Exception:
        return None
    return None


class _DoHAdapter(requests.adapters.HTTPAdapter):
    """Pool por IP com SNI/cert do hostname real (sessão single-host)."""

    def __init__(self, host: str, **kw):
        self.host = host
        super().__init__(**kw)

    def init_poolmanager(self, *args, **kw):
        kw["server_hostname"] = self.host
        super().init_poolmanager(*args, **kw)


class _BrowserTransport:
    """HTTP pela stack do browser, via fetch dentro da página.

    page.evaluate roda no processo do Firefox: usa o DoH configurado no
    browser (o sistema não resolve *.sigma.st) e o fingerprint TLS real —
    é o combo que passa no Cloudflare (o APIRequestContext do Playwright
    não serve: resolve DNS no Node e morre no getaddrinfo).
    """

    def __init__(self, page):
        self._page = page

    def get(self, url, params=None, headers=None, timeout=None):
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"
        status, text = self._page.evaluate(
            "async ([u, h]) => { const r = await fetch(u, {headers: h});"
            " return [r.status, await r.text()]; }",
            [url, headers or {}],
        )
        return _BrowserResponse(status, text)


class _BrowserResponse:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def json(self):
        import json as _json
        return _json.loads(self.text)


class SigmaApiError(RuntimeError):
    def __init__(self, path: str, status: int, body: str):
        self.status = status
        super().__init__(f"Sigma API {path} -> {status}: {body[:_BODY_SNIPPET]}")


class SigmaApiClient:
    """GET-only na API do Sigma com token de sigma_session.json.

    `transport=None` usa requests (motor de teste; CF bloqueia em produção).
    Produção: use `open_client()`, que injeta o transporte do browser.
    """

    def __init__(self, token: str = None, session_path: str = "sigma_session.json",
                 transport=None):
        self.session_path = session_path
        self._doh_ip: str | None = None
        self._browser = transport is not None
        self._session = transport if transport is not None else requests.Session()
        if not self._browser:
            self._session.headers["User-Agent"] = _UA
        if token:
            self.token = token
            self._apply_session_cookies(load_session(session_path))
        else:
            self.token = self._ensure_token()

    # ---- boot ----------------------------------------------------------------

    def _ensure_token(self) -> str:
        """Token válido do arquivo; morto/ausente → relogin browser (se der)."""
        sess = load_session(self.session_path)
        if sess and self._status_of("/auth/me", sess["token"]) == 200:
            self._apply_session_cookies(sess)
            return sess["token"]
        typer.secho("⚠ Token ausente/inválido — refazendo login no browser...", fg=typer.colors.YELLOW)
        with ensure_logged_page(session_path=self.session_path):
            pass  # o contexto já reloga e salva quando a sessão está morta
        sess = load_session(self.session_path)
        if not sess:
            raise RuntimeError("Sem sessão após relogin. Rode: venv/bin/python main.py sigma-login --save")
        self._apply_session_cookies(sess)
        return sess["token"]

    def _apply_session_cookies(self, sess: dict | None):
        if self._browser:
            return  # cookies já estão no contexto do browser (ensure_logged_page)
        if not sess:
            return
        for c in sess.get("cookies", []):
            self._session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

    # ---- transporte ----------------------------------------------------------

    def _via_doh_ip(self) -> str | None:
        """Resolve via DoH e monta o adapter por-IP. None se nem DoH resolver."""
        ip = doh_resolve(SIGMA_HOST)
        if not ip:
            return None
        self._doh_ip = ip
        self._session.mount("https://", _DoHAdapter(SIGMA_HOST))
        typer.secho(f"⚠ DNS do sistema falhou p/ {SIGMA_HOST} — DoH -> {ip}", fg=typer.colors.YELLOW)
        return ip

    def _request(self, path: str, params: dict | None = None) -> requests.Response:
        auth = {"Authorization": f"Bearer {self.token}"}
        if self._browser:
            return self._session.get(f"{SIGMA_API}{path}", params=params,
                                     headers=auth, timeout=30_000)
        self._session.headers["Authorization"] = auth["Authorization"]
        if self._doh_ip:  # DNS já falhou antes: vai direto por IP
            return self._session.get(
                f"https://{self._doh_ip}/api{path}",
                params=params, headers={"Host": SIGMA_HOST}, timeout=30,
            )
        try:
            return self._session.get(f"{SIGMA_API}{path}", params=params, timeout=30)
        except requests.exceptions.ConnectionError as exc:
            if not _is_dns_failure(exc):
                raise
            ip = self._via_doh_ip()
            if not ip:
                raise
            return self._session.get(
                f"https://{ip}/api{path}", params=params,
                headers={"Host": SIGMA_HOST}, timeout=30,
            )

    def _status_of(self, path: str, token: str) -> int:
        self.token = token
        try:
            return self._request(path).status_code
        except SigmaApiError:
            return -1

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        r = self._request(path, params)
        if r.status_code != 200:
            raise SigmaApiError(path, r.status_code, r.text)
        try:
            return r.json()
        except ValueError:
            raise SigmaApiError(path, r.status_code, f"corpo não-JSON: {r.text}")

    # ---- endpoints mapeados (PANEL_MAP.md) -----------------------------------

    def me(self) -> dict:
        return self._get("/auth/me")

    def customers(self, page: int = 1, per_page: int = 15) -> dict:
        return self._get("/customers", params={"page": page, "per_page": per_page})

    def customers_expiring(self) -> dict:
        return self._get("/customers/expiring")

    def customers_statistics(self) -> dict:
        return self._get("/customers/statistics")

    def customers_top10(self, from_date: str, to_date: str) -> dict:
        return self._get("/customers/statistics/top10",
                         params={"from_date": from_date, "to_date": to_date})

    def resellers(self) -> list:
        return self._get("/resellers/list")

    def notices(self) -> dict:
        return self._get("/notices/list")

    def dashboard_chart(self, name: str) -> dict:
        return self._get(f"/dashboard/charts/{name}")

    def dashboard_recovery(self) -> dict:
        return self._get("/dashboard/metrics/recovery")

    def ai_analysis(self) -> dict:
        return self._get("/dashboard/ai-analysis")

    def settings_public(self) -> dict:
        return self._get("/settings/public")


@contextmanager
def open_client(session_path: str = "sigma_session.json", proxy: str = None):
    """
    Cliente com transporte do browser (o único que o Cloudflare aceita).

    Abre o browser com a sessão salva (reutiliza se válida, senão refaz
    login), injeta cookies no contexto e devolve o client. As chamadas
    /api/* passam pelo TLS real do Firefox sem renderizar página.
    """
    with ensure_logged_page(session_path=session_path, proxy=proxy) as s:
        transport = _BrowserTransport(s.page)
        yield SigmaApiClient(token=s.token, session_path=session_path, transport=transport)
