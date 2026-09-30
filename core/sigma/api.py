"""
Cliente da API do painel Sigma.

Leitura: só GET, um por endpoint mapeado em explore/PANEL_MAP.md.
MUTAÇÃO: apenas 4 métodos curated (ciclo de vida validado no explore 07):
create/update/resync/delete de cliente — sem endpoints bulk (mass-delete,
move, migration ficam de fora por decisão de segurança).

TRANSPORTE: o Cloudflare exige fingerprint de browser (requests puro toma
403 "Just a moment"), então o caminho padrão é `open_client()`: browser via
Playwright e as chamadas passam por fetch DENTRO da página (TLS real + DoH
do browser, sem renderizar nada). O motor requests+DoH permanece como
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
# Sem esses headers, mutações fazem o Laravel responder validação com
# 302 → HTML status 200 (parece sucesso, não fez nada). Descoberta do 07.
_AXIOS_HEADERS = {
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

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

    def __init__(self, page, extra_headers: dict | None = None):
        self._page = page
        self._extra = extra_headers or {}

    def get(self, url, params=None, headers=None, timeout=None):
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"
        merged = {**self._extra, **(headers or {})}
        status, text = self._page.evaluate(
            "async ([u, h]) => { const r = await fetch(u, {headers: h});"
            " return [r.status, await r.text()]; }",
            [url, merged],
        )
        return _BrowserResponse(status, text)

    def request(self, method, url, json=None, headers=None, timeout=None):
        """Mutações: fetch com method + body JSON (mesma assinatura do requests)."""
        import json as _json
        merged = {**self._extra, **(headers or {})}
        status, text = self._page.evaluate(
            "async ([u, h, m, b]) => { const r = await fetch(u,"
            " {method: m, headers: h, body: b});"
            " return [r.status, await r.text()]; }",
            [url, merged, method.upper(),
             _json.dumps(json) if json is not None else None],
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

    def _mutate(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        """Mutação com headers axios (sem eles o Laravel responde 302→HTML
        com status 200 — parece sucesso e não faz nada; descoberta do 07)."""
        headers = dict(_AXIOS_HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = f"Bearer {self.token}"
        r = self._session.request(
            method, f"{SIGMA_API}{path}", json=payload, headers=headers,
            timeout=30_000 if self._browser else 30,
        )
        if r.status_code not in (200, 201):
            raise SigmaApiError(path, r.status_code, r.text)
        try:
            return r.json()
        except ValueError:
            raise SigmaApiError(path, r.status_code, f"corpo não-JSON: {r.text}")

    # ---- endpoints mapeados (PANEL_MAP.md) -----------------------------------

    def me(self) -> dict:
        return self._get("/auth/me")

    def customers(self, page: int = 1, per_page: int = 100) -> dict:
        """
        Lista paginada de clientes.

        ponytail: a API IGNORA o param snake_case `per_page` (silencioso —
        volta sempre 15/página); o honrado é camelCase `perPage`, com cap
        de 100/linha verificado ao vivo (341 clientes -> 4 págs).
        """
        return self._get("/customers", params={"page": page, "perPage": per_page})

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

    # ---- mutações (ciclo de vida validado no explore 07) ----------------------

    def create_customer(self, payload: dict) -> dict | list:
        """POST /customers — cria cliente. 201 {data:{id}}; 422 JSON nomeia
        campos obrigatórios. Schema mínimo validado no 07: username, password,
        password_confirmation, name, email, connections, server_id, package_id
        (password: só letras/números/-/@/_)."""
        return self._mutate("POST", "/customers", payload)

    def update_customer(self, customer_id: str, payload: dict) -> dict | list:
        """PUT /customers/{id} — edita; envie o payload completo (create) + mudanças."""
        return self._mutate("PUT", f"/customers/{customer_id}", payload)

    def resync_customer(self, customer_id: str) -> dict | list:
        return self._mutate("POST", f"/customers/{customer_id}/resync", {})

    def delete_customer(self, customer_id: str) -> dict | list:
        """DELETE /customers/{id} — SOFT delete (resposta traz deleted_at;
        restore existe em POST /customers/restore, ainda não testado)."""
        return self._mutate("DELETE", f"/customers/{customer_id}")


@contextmanager
def open_client(session_path: str = "sigma_session.json", proxy: str = None):
    """
    Cliente com transporte do browser (o único que o Cloudflare aceita).

    Abre o browser com a sessão salva (reutiliza se válida, senão refaz
    login), injeta cookies no contexto e devolve o client. As chamadas
    /api/* passam pelo TLS real do Firefox sem renderizar página.
    """
    with ensure_logged_page(session_path=session_path, proxy=proxy) as s:
        transport = _BrowserTransport(s.page, extra_headers=_AXIOS_HEADERS)
        yield SigmaApiClient(token=s.token, session_path=session_path, transport=transport)
