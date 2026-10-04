"""
Cliente base da API dos painéis da família Sigma (sigma/woodcine/blackbr).

Toda a lógica vive aqui — os módulos core/<site>/api.py são só config
(API_BASE, classe de erro, flag de vendor) + subclasses mínimas. Regra do
AGENTS.md (G5): correção vai no BASE, não nas cópias.

Leitura: só GET, um por endpoint mapeado em explore/PANEL_MAP.md.
MUTAÇÃO: apenas 4 métodos curated (ciclo de vida validado no explore 07):
create/update/resync/delete de cliente — sem endpoints bulk (mass-delete,
move, migration ficam de fora por decisão de segurança).

TRANSPORTE: o Cloudflare exige fingerprint de browser (requests puro toma
403 "Just a moment"), então o caminho padrão é `open_client_for()`: browser
via Playwright e as chamadas passam por fetch DENTRO da página (TLS real +
DoH do browser, sem renderizar nada). O motor requests+DoH permanece como
fallback/motor de teste (unit tests), mas é bloqueado pelo CF em produção.

Auth: token de <site>_session.json (auth.load_session), "Authorization:
Bearer". `ensure_logged_page` reutiliza a sessão salva ou refaz o login no
browser — validade é decisão do servidor (/api/auth/me).
"""
from contextlib import contextmanager
import json
import threading
import time
from urllib.parse import quote

import requests
import typer


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
_DOH_TTL = 300  # s — pin de IP expira; Cloudflare rotaciona IPs (CR-21)


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
    browser e o fingerprint TLS real — é o combo que passa no Cloudflare
    (o APIRequestContext do Playwright não serve: resolve DNS no Node e
    morre no getaddrinfo).
    """

    def __init__(self, page, extra_headers: dict | None = None):
        self._page = page
        self._extra = extra_headers or {}

    _FETCH_JS = (
        "async ([u, h, m, b, t]) => {"
        " try { const r = await fetch(u, { method: m, headers: h,"
        " body: b, signal: AbortSignal.timeout(t) });"
        " return [r.status, await r.text()]; }"
        " catch (e) { return e.name === 'AbortError' ? ['TIMEOUT', ''] :"
        " Promise.reject(e); } }"
    )

    def _fetch(self, url, headers, method="GET", body=None, timeout=None):
        """fetch com timeout REAL — AbortSignal (CR-05: antes o timeout era
        placebo, o fetch ficava pendurado pra sempre) + watchdog M10: o
        AbortSignal só cobre o fetch; uma main thread de SPA travada pendura
        o evaluate em si. O vigia fecha a página, derrubando o evaluate."""
        ms = timeout if timeout is not None else 30_000

        def _kill():
            try:
                self._page.close()
            except Exception:
                pass

        watchdog = threading.Timer(ms / 1000 + 5, _kill)
        watchdog.daemon = True
        watchdog.start()
        try:
            return self._page.evaluate(
                self._FETCH_JS,
                [url, headers, method,
                 json.dumps(body) if body is not None else None, ms],
            )
        finally:
            watchdog.cancel()

    def get(self, url, params=None, headers=None, timeout=None):
        if params:
            from urllib.parse import urlencode
            url = f"{url}?{urlencode(params)}"
        merged = {**self._extra, **(headers or {})}
        status, text = self._fetch(url, merged, "GET", None, timeout)
        if status == "TIMEOUT":
            raise TimeoutError(f"fetch sem resposta em {timeout or 30_000}ms: {url}")
        return _BrowserResponse(status, text)

    def request(self, method, url, json=None, headers=None, timeout=None):
        """Mutações: fetch com method + body JSON (mesma assinatura do requests)."""
        import json as _json
        merged = {**self._extra, **(headers or {})}
        status, text = self._fetch(url, merged, method.upper(), json, timeout)
        if status == "TIMEOUT":
            raise TimeoutError(f"fetch sem resposta em {timeout or 30_000}ms: {url}")
        return _BrowserResponse(status, text)


class _BrowserResponse:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text

    def json(self):
        import json as _json
        return _json.loads(self.text)


class _HttpTransport:
    """HTTP direto via curl_cffi (impersonate=chrome) — sync dezenas de vezes
    mais rápido que o browser. Mesma interface do _BrowserTransport; cookies e
    token vêm do session json existente (painéis Bearer-only como newmais têm
    cookies=[] e funcionam só com Bearer). Se o Cloudflare barrar (403 /
    challenge), o caller cai no fallback browser (open_client_for mode 'auto'
    = self-healing)."""

    def __init__(self, token: str, cookies: list, extra_headers: dict = None):
        self._token = token
        self._cookiejar = {
            c["name"]: c["value"]
            for c in (cookies or [])
            if c.get("name") and c.get("value")
        }
        self._extra = dict(extra_headers or {})
        self._doh = {}  # host -> (ip, ts) — cache DoH TTL 5min
        self._session = None  # cffi.Session lazy — pool keep-alive por host
        self._resolve = []  # entradas CurlOpt.RESOLVE acumuladas na session

    def _headers(self, headers: dict | None) -> dict:
        return {**self._extra, **(headers or {})}

    def _call(self, method, url, params=None, json=None, headers=None, timeout=None):
        from urllib.parse import urlparse

        try:
            from curl_cffi import requests as cffi
            from curl_cffi.const import CurlOpt
        except ImportError as e:  # B3: erro orientado, não ImportError cru
            raise RuntimeError(
                "curl_cffi não instalado — transporte HTTP indisponível "
                "(venv/bin/pip install curl_cffi) ou use transport='browser'.") from e

        # DNS local não resolve os hosts dos painéis (ISP) — resolve via DoH
        # (mesmo esquema do browser: dns.google) e fixa o IP no RESOLVE.
        # RESOLVE vai no curl_options da SESSION (setado UMA vez por host,
        # re-aplicado pela lib pós-reset) — curl_options POR REQUEST mata o
        # pool de conexões (rodada 1: 47s → 72s).
        host = urlparse(url).hostname or ""
        if self._session is None:
            self._session = cffi.Session(
                impersonate="chrome", cookies=self._cookiejar)
        if host:
            ip, ts = self._doh.get(host, (None, 0.0))
            ttl = 300 if ip else 30
            if not ip or time.time() - ts > ttl:
                ip = doh_resolve(host)
                self._doh[host] = (ip, time.time())
                if ip:
                    self._resolve = [e for e in self._resolve
                                     if e.split(":")[0] != host]
                    self._resolve += [f"{host}:443:{ip}", f"{host}:80:{ip}"]
                    self._session.curl_options = {
                        CurlOpt.RESOLVE: list(self._resolve)}

        # B2: >=1000 é ms; abaixo é segundos já
        t = timeout / 1000 if (timeout or 0) >= 1000 else (timeout or 30)
        r = self._session.request(
            method, url, params=params, json=json,
            headers=self._headers(headers), timeout=t,
        )
        return _BrowserResponse(r.status_code, r.text)

    def get(self, url, params=None, headers=None, timeout=None):
        return self._call("GET", url, params=params, headers=headers, timeout=timeout)

    def request(self, method, url, json=None, headers=None, timeout=None):
        return self._call(method, url, json=json, headers=headers, timeout=timeout)


class PanelApiError(RuntimeError):
    def __init__(self, path: str, status: int, body: str, vendor: str = "Panel"):
        self.status = status
        super().__init__(f"{vendor} API {path} -> {status}: {body[:_BODY_SNIPPET]}")


class PanelApiClient:
    """GET-only na API do painel com token de <site>_session.json.

    Subclasse por site define: API_BASE, HOST, API_ERROR, VENDOR,
    DEFAULT_SESSION_FILE, _AUTH (módulo auth do site — late binding pra
    monkeypatch funcionar) e opcionalmente UPDATE_STRIP_FIELDS.

    `transport=None` usa requests (motor de teste; CF bloqueia em produção).
    Produção: use `open_client_for()`, que injeta o transporte do browser.
    """

    API_BASE: str = ""
    HOST: str = ""
    VENDOR: str = "panel"
    API_ERROR = PanelApiError
    DEFAULT_SESSION_FILE = ""
    UPDATE_STRIP_FIELDS = False
    # transporte HTTP direto (curl_cffi) no mode 'auto' — ligar por painel
    # SOMENTE após validar sync HTTP vs browser (contagens idênticas).
    FAST_SYNC = False
    _AUTH = None  # módulo auth do site (load_session/ensure_logged_page/default_proxy)

    def __init__(self, token: str = None, session_path: str = None,
                 transport=None):
        self.session_path = session_path or type(self).DEFAULT_SESSION_FILE
        # atributo existe desde o boot: _ensure_token -> _status_of faz swap
        # de self.token antes do __init__ terminar de defini-lo.
        self._doh_ip: str | None = None
        self._doh_ts: float = 0.0
        self.token = token
        self._browser = transport is not None
        self._session = transport if transport is not None else requests.Session()
        if not self._browser:
            self._session.headers["User-Agent"] = _UA
        if token:
            self._apply_session_cookies(type(self)._AUTH.load_session(self.session_path))
        else:
            self.token = self._ensure_token()

    # ---- boot ----------------------------------------------------------------

    def _ensure_token(self) -> str:
        """Token válido do arquivo; morto/ausente → relogin browser (se der)."""
        auth = type(self)._AUTH
        sess = auth.load_session(self.session_path)
        if sess and self._status_of("/auth/me", sess["token"]) == 200:
            self._apply_session_cookies(sess)
            return sess["token"]
        typer.secho("⚠ Token ausente/inválido — refazendo login no browser...", fg=typer.colors.YELLOW, err=True)
        with auth.ensure_logged_page(session_path=self.session_path):
            pass  # o contexto já reloga e salva quando a sessão está morta
        sess = auth.load_session(self.session_path)
        if not sess:
            raise RuntimeError(
                f"Sem sessão após relogin. Rode: venv/bin/python main.py {type(self).VENDOR}-login --save")
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
        host = type(self).HOST
        # late binding: patch de doh_resolve no módulo do SITE é honrado
        # (mesmo mecanismo do _AUTH; testes monkeypatcheam o módulo do site)
        _mod = type(self)._AUTH
        ip = (_mod.doh_resolve if _mod else doh_resolve)(host)
        if not ip:
            return None
        self._doh_ip = ip
        self._doh_ts = time.monotonic()
        self._session.mount("https://", _DoHAdapter(host))
        typer.secho(f"⚠ DNS do sistema falhou p/ {host} — DoH -> {ip}", fg=typer.colors.YELLOW, err=True)
        return ip

    def _request(self, path: str, params: dict | None = None) -> requests.Response:
        auth = {"Authorization": f"Bearer {self.token}"}
        if self._browser:
            return self._session.get(f"{type(self).API_BASE}{path}", params=params,
                                     headers=auth, timeout=30_000)
        self._session.headers["Authorization"] = auth["Authorization"]
        if self._doh_ip and time.monotonic() - self._doh_ts < _DOH_TTL:
            # DNS já falhou antes: vai direto por IP (pin expira em _DOH_TTL)
            return self._session.get(
                f"https://{self._doh_ip}/api{path}",
                params=params, headers={"Host": type(self).HOST}, timeout=30,
            )
        try:
            return self._session.get(f"{type(self).API_BASE}{path}", params=params, timeout=30)
        except requests.exceptions.ConnectionError as exc:
            if not _is_dns_failure(exc):
                raise
            ip = self._via_doh_ip()
            if not ip:
                raise
            return self._session.get(
                f"https://{ip}/api{path}", params=params,
                headers={"Host": type(self).HOST}, timeout=30,
            )

    def _status_of(self, path: str, token: str) -> int:
        """Proba o token SEM alterar estado (CR-06: antes mutava self.token
        e o except ApiError era código morto — falhas de request levantam
        ConnectionError/Timeout, não ApiError)."""
        old, self.token = self.token, token
        try:
            return self._request(path).status_code
        except Exception:
            return -1
        finally:
            self.token = old

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        r = self._request(path, params)
        if r.status_code != 200:
            raise type(self).API_ERROR(path, r.status_code, r.text)
        try:
            return r.json()
        except ValueError:
            raise type(self).API_ERROR(path, r.status_code, f"corpo não-JSON: {r.text}")

    def _mutate(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        """Mutação com headers axios (sem eles o Laravel responde 302→HTML
        com status 200 — parece sucesso e não faz nada; descoberta do 07)."""
        headers = dict(_AXIOS_HEADERS)
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = f"Bearer {self.token}"
        r = self._session.request(
            method, f"{type(self).API_BASE}{path}", json=payload, headers=headers,
            timeout=30_000 if self._browser else 30,
        )
        if r.status_code not in (200, 201, 204):
            raise type(self).API_ERROR(path, r.status_code, r.text)
        if r.status_code == 204:  # no content — nada pra parsear (CR-22)
            return {}
        try:
            return r.json()
        except ValueError:
            raise type(self).API_ERROR(path, r.status_code, f"corpo não-JSON: {r.text}")

    # ---- endpoints mapeados (PANEL_MAP.md) -----------------------------------

    def me(self) -> dict:
        return self._get("/auth/me")

    def customers(self, page: int = 1, per_page: int = 100) -> dict:
        """
        Lista paginada de clientes.

        ponytail: a API IGNORA o param snake_case `per_page` (silencioso —
        volta sempre 15/página); o honrado é camelCase `perPage`, com cap
        de 100/linha verificado ao vivo.
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
        return self._get(f"/dashboard/charts/{quote(str(name), safe='')}")

    def dashboard_recovery(self) -> dict:
        return self._get("/dashboard/metrics/recovery")

    def ai_analysis(self) -> dict:
        return self._get("/dashboard/ai-analysis")

    def settings_public(self) -> dict:
        return self._get("/settings/public")

    def servers(self) -> list:
        """GET /servers — catálogo de servidores."""
        return self._get("/servers")

    def packages(self) -> list:
        """GET /packages/list — catálogo de pacotes (campo server_id liga ao
        server e valida o par p/ create). GET /packages puro é 403."""
        return self._get("/packages/list")

    # ---- mutações (ciclo de vida validado no explore 07) ----------------------

    def create_customer(self, payload: dict) -> dict | list:
        """POST /customers — cria cliente. 201 {data:{id}}; 422 JSON nomeia
        campos obrigatórios. Schema mínimo validado no 07: username, password,
        password_confirmation, name, email, connections, server_id, package_id
        (password: só letras/números/-/@/_)."""
        return self._mutate("POST", "/customers", payload)

    def update_customer(self, customer_id: str, payload: dict) -> dict | list:
        """PUT /customers/{id} — edita; envie o payload completo (create) + mudanças.

        Vendor blackbr (descoberta do lifecycle 07): o update PROÍBE
        username/password/password_confirmation — retorna 422 'The username
        field is prohibited.'. A flag UPDATE_STRIP_FIELDS (só blackbr) remove
        os campos proibidos no ponto único."""
        if type(self).UPDATE_STRIP_FIELDS:
            payload = {k: v for k, v in payload.items()
                       if k not in ("username", "password", "password_confirmation")}
        return self._mutate("PUT", f"/customers/{quote(str(customer_id), safe='')}", payload)

    def resync_customer(self, customer_id: str) -> dict | list:
        return self._mutate("POST", f"/customers/{quote(str(customer_id), safe='')}/resync", {})

    def customer_playlist(self, customer_id: str) -> dict | list:
        # GET /customers/{id}/playlist — rota igual nos 4 painéis sigma.
        # Retorna templates por idioma (mensagem fallback se o admin não
        # configurou template para o servidor do cliente).
        return self._get(f"/customers/{quote(str(customer_id), safe='')}/playlist")

    def delete_customer(self, customer_id: str) -> dict | list:
        """DELETE /customers/{id} — SOFT delete (resposta traz deleted_at;
        restore existe em POST /customers/restore, ainda não testado)."""
        return self._mutate("DELETE", f"/customers/{quote(str(customer_id), safe='')}")


def find_customer(client, customer_id: str) -> dict | None:
    """Procura o cliente pelo id paginando /customers (perPage=100)."""
    page = 1
    while True:
        resp = client.customers(page=page)
        for row in resp.get("data", []):
            if str(row.get("id")) == str(customer_id):  # CR-20: IDs são strings
                return row
        if page >= resp.get("meta", {}).get("last_page", 1):
            return None
        page += 1


def search_customers(client, term: str, max_pages: int = 25) -> list[dict]:
    """Busca PARCIAL de clientes na API (username/name/email contém termo).

    Diferente de find_customer (id exato). Fast path: GET /customers?username=
    filtra server-side (validado ao vivo 04/10/2026: contém, honra ausência);
    aceito só se total bate com 1 página inteira e toda row contém o termo.
    Clientes/fakes sem _get (só .customers paginado) caem no fallback:
    paginamos e filtramos aqui.
    """
    term = term.strip().lower()
    if not term:
        return []
    if hasattr(client, "_get"):
        resp = client._get("/customers", params={"page": 1, "perPage": 100, "username": term})
        rows = resp.get("data", [])
        total = resp.get("meta", {}).get("total")
        matches = [
            r for r in rows
            if term in " ".join(str(r.get(k, "")) for k in ("username", "name", "email")).lower()
        ]
        if total is not None and total == len(rows) <= 100 and len(matches) == len(rows):
            return rows
    hits, page = [], 1
    while page <= max_pages:
        resp = client.customers(page=page)
        rows = resp.get("data", [])
        for row in rows:
            hay = " ".join(
                str(row.get(k, "")) for k in ("username", "name", "email")
            ).lower()
            if term in hay:
                hits.append(row)
        last_page = resp.get("meta", {}).get("last_page")
        if not rows or (last_page is not None and page >= last_page):
            break
        page += 1
    return hits


# Campos seguros para exibir um cliente (allowlist). NUNCA password,
# m3u_url/renew_url — a URL do M3U embute a senha do cliente nela.
CUSTOMER_PUBLIC_FIELDS = (
    "id", "username", "name", "email", "status", "expires_at",
    "connections", "note", "server_name", "package_name",
    "is_trial", "created_at",
)


def project_customer(row) -> dict:
    """Projeção segura de um row de cliente p/ exibição (conselho: resync
    devolve o row COMPLETO com password/m3u_url — nunca ecoar cru)."""
    if not isinstance(row, dict):
        return {"raw": str(row)[:200]}
    return {k: row.get(k) for k in CUSTOMER_PUBLIC_FIELDS if k in row}


def customer_new_expiry(row: dict, add_days: int = 0, set_date: str = None) -> str | None:
    """Nova expiração (YYYY-MM-DD) a partir do row atual (+ N dias ou data fixa).

    CR-04: `expires_at` é 02:59:59Z do dia SEGUINTE (23:59:59 local, painel
    fixo UTC-3) — a data local real é `[:10]` menos 1 dia. Sem subtrair,
    cada renovação adiciona +1 dia fantasma cumulativo.
    """
    from datetime import datetime, timedelta

    if set_date:
        base = datetime.strptime(set_date, "%Y-%m-%d")
    elif row.get("expires_at"):
        # A4: canônico primeiro (o writer set_expiry_on_payload trata
        # expires_at como canônico — ler na mesma ordem, senão row com
        # ambas as chaves renova a partir da data velha).
        base = datetime.strptime(row["expires_at"][:10], "%Y-%m-%d") - timedelta(days=1)
    elif row.get("expiry_date"):
        base = datetime.strptime(row["expiry_date"][:10], "%Y-%m-%d")
    elif row.get("due_date"):
        base = datetime.strptime(row["due_date"][:10], "%Y-%m-%d")
    else:
        return None
    return (base + timedelta(days=add_days)).strftime("%Y-%m-%d")


def set_expiry_on_payload(row: dict, payload: dict, ymd: str):
    """Grava a expiração na chave que o row usa. O campo canônico é
    `expires_at` (ISO); painel fixo em UTC-3 — o renewal nativo grava
    23:59:59 local = 02:59:59Z do dia seguinte. expiry_date/due_date são
    variantes que ainda circulam em alguns rows."""
    from datetime import datetime, timedelta

    # CR-19: `expires_at` é o campo canônico — testa PRIMEIRO e limpa as
    # variantes concorrentes pra não sobrar expiry velho no payload.
    if "expires_at" in row:
        nxt = (datetime.strptime(ymd, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        payload["expires_at"] = f"{nxt}T02:59:59.000000Z"
        payload.pop("expiry_date", None)
        payload.pop("due_date", None)
    elif "expiry_date" in row:
        payload["expiry_date"] = ymd
        payload.pop("due_date", None)
    elif "due_date" in row:
        payload["due_date"] = ymd
    else:
        raise ValueError("row sem campo de expiração conhecido")


@contextmanager
def open_client_for(cls, session_path: str = None, proxy: str = None, guard=None,
                    transport: str = None):
    """
    Cliente com transporte do browser (o único que o Cloudflare aceita).

    Abre o browser com a sessão salva (reutiliza se válida, senão refaz
    login), injeta cookies no contexto e devolve o client. As chamadas
    /api/* passam pelo TLS real do Firefox sem renderizar página.

    proxy: se None, usa SIGMA_PROXY do ambiente (ex. Termux+microsocks via
    Tailscale: socks5://100.x.y.z:1080). cf_clearance é IP-bound — mantenha
    o caminho estável depois do primeiro login.
    """
    auth = cls._AUTH
    mode = transport or ("auto" if cls.FAST_SYNC else "browser")

    # A2: guard é kill switch de rede no browser — sem page ele não existe.
    if guard is not None and mode in ("http", "auto"):
        raise RuntimeError(
            "guard só funciona com browser (precisa de page para interceptar "
            "requests) — use transport='browser' ou omita o guard.")

    def _resolve_session_path():
        # M1: multi-conta — http/auto precisam da MESMA conta ativa que o
        # browser usaria (SIGMA_ACCOUNT > last_good > primeira do arquivo).
        if session_path:
            return session_path
        try:
            accounts = auth.load_accounts()
            if accounts:
                active = auth.resolve_active_account(accounts)
                if active:
                    return auth.session_path_for(active["username"], accounts)
        except Exception:
            pass  # auth sem multi-conta — cai no default
        return cls.DEFAULT_SESSION_FILE

    def http_client(sess):
        return cls(token=sess["token"],
                   session_path=session_path or cls.DEFAULT_SESSION_FILE,
                   transport=_HttpTransport(sess["token"], sess.get("cookies") or [],
                                            extra_headers=_AXIOS_HEADERS))

    if mode == "http":
        sess = auth.load_session(_resolve_session_path())
        if not sess:
            raise RuntimeError(
                f"Sem sessão válida — rode main.py {cls.VENDOR}-login --save primeiro.")
        yield http_client(sess)
        return

    if mode == "auto":
        # self-healing: sessão salva + probe barato; CF barrando → browser
        # (A1: _request devolve Response cru — _get devolve JSON parseado e
        # .status_code em dict é AttributeError, o que derrubava o probe
        # silenciosamente e mandava TUDO pro browser).
        # FIX noturno: o try/except cobre SÓ o probe — o yield NÃO pode ficar
        # dentro dele, senão exceção do CORPO do `with` é engolida e o
        # contextmanager cai no browser gerando "generator didn't stop
        # after throw()" (mascara o erro real do chamador).
        try:
            sess = auth.load_session(_resolve_session_path())
        except Exception:
            sess = None
        if sess:
            probe = http_client(sess)
            try:
                probe_ok = probe._request("/auth/me").status_code == 200
            except Exception:
                probe_ok = False
            if probe_ok:
                yield probe
                return
    with auth.ensure_logged_page(session_path=session_path,
                                 proxy=proxy or auth.default_proxy(), guard=guard) as s:
        transport = _BrowserTransport(s.page, extra_headers=_AXIOS_HEADERS)
        # s.session_path é o caminho RESOLVIDO (multi-conta: pode ser o
        # dotfile de uma conta secundária) — _ensure_token recarrega dele.
        yield cls(token=s.token, session_path=s.session_path, transport=transport)


def project_response(res) -> dict:
    """M2: projeção segura de resposta de mutação — o row completo pode
    conter password do cliente; só os campos inofensivos saem."""
    if isinstance(res, dict):
        return {k: res[k] for k in ("id", "deleted_at", "status") if k in res}
    return {"raw": str(res)[:200]}
