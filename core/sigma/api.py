"""
Cliente HTTP read-only da API do painel Sigma.

Segurança por construção: só existem métodos GET, um por endpoint mapeado
em explore/PANEL_MAP.md. Nenhuma superfície de mutação.

Auth: token de sigma_session.json (auth.load_session), enviado como
"Authorization: Bearer". Validado com /api/auth/me; se morto, refaz login
pelo browser (ensure_logged_page) quando houver env creds.

DNS: este host só resolve via DoH do Google. Em falha de resolução,
consultamos dns.google e reconectamos por IP com SNI/cert do hostname real
(HTTPSConnectionPool(ip, server_hostname=...) — suportado no urllib3 2.x).

ponytail: Cloudflare pode barrar UA não-browser mesmo com cf_clearance (o
fingerprint TLS do requests difere do browser). Se um 403 HTML aparecer, o
plano B é reusar o APIRequestContext do Playwright (context.request), que
herda cookies/TLS do browser — só construa se isso acontecer.
"""
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


class SigmaApiError(RuntimeError):
    def __init__(self, path: str, status: int, body: str):
        self.status = status
        super().__init__(f"Sigma API {path} -> {status}: {body[:_BODY_SNIPPET]}")


class SigmaApiClient:
    """GET-only na API do Sigma com token de sigma_session.json."""

    def __init__(self, token: str = None, session_path: str = "sigma_session.json"):
        self.session_path = session_path
        self._doh_ip: str | None = None
        self._session = requests.Session()
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
        self._session.headers["Authorization"] = f"Bearer {self.token}"
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
