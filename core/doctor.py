"""
Diagnóstico do ambiente do hub — engine genérico (verde/amarelo/vermelho).

Checagens (todas LOCAIS exceto --net):
  venv      — interpretador do venv existe e a versão de Python é adequada
  database  — banco existe, tabelas esperadas presentes, contagens por tabela
  join      — integridade dos symlinks do repo privado (ok/quebrado/ausente)
  sessions  — *_session.json: token presente (NUNCA ecoado) + idade do arquivo
  env       — SIGMA_ALLOW_DESTRUCTIVE ligado é VERMELHO; HUB_DISPLAY válido
  deps      — curl_cffi (FAST_SYNC), openpyxl (xlsx), camoufox/playwright (browser)
  sites     — (só --net) healthcheck GET puro /auth/me por site com sessão;
              403/429 = amarelo (Cloudflare — fallback browser), NUNCA insistir

Site discovery genérico: todo core/<pkg> com auth.py é um site; o arquivo de
sessão é qualquer attr do módulo terminando em '_session.json'; probe HTTP
só para sites com PanelApiClient (família sigma) — os demais (ex.: Django)
ficam na checagem de sessão, sem probe.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import inspect
import os
import pkgutil
from dataclasses import dataclass

from core import database
from core.http_retry import CloudflareBlocked

REPO_ROOT = database.DB_PATH.rsplit("/", 1)[0]

#: dias de idade de session.json: verde até 7, amarelo até 30, vermelho depois
_SESSION_FRESH_DAYS = 7
_SESSION_OLD_DAYS = 30

_BASE_MODULES = {
    "automations", "alerts", "browser", "database", "doctor", "exports",
    "guard", "http_retry", "panel_api", "panel_auth", "panel_scraper",
    "snapshots",
}


@dataclass
class CheckResult:
    name: str
    status: str  # ok | warn | fail
    detail: str


def summary(results: list[CheckResult]) -> dict:
    s = {"ok": 0, "warn": 0, "fail": 0}
    for r in results:
        s[r.status] = s.get(r.status, 0) + 1
    return s


# ---- checks individuais ------------------------------------------------------

def check_python() -> CheckResult:
    import sys
    v = sys.version_info
    if (v.major, v.minor) >= (3, 10):
        return CheckResult("python", "ok", f"Python {v.major}.{v.minor}.{v.micro}")
    return CheckResult("python", "fail",
                       f"Python {v.major}.{v.minor} < 3.10 (README: Quick start)")


def check_database(db_path: str | None = None) -> CheckResult:
    path = db_path or database.DB_PATH
    if not os.path.exists(path):
        return CheckResult("database", "fail",
                           f"banco ausente: {path} (rode main.py uma vez: init_db)")
    import sqlite3
    conn = sqlite3.connect(path, timeout=5)
    try:
        tabelas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        faltando = {"raw_snapshots", "products", "panel_entities"} - tabelas
        if faltando:
            return CheckResult("database", "fail",
                               f"tabelas ausentes: {', '.join(sorted(faltando))}")
        ents = conn.execute("SELECT COUNT(*) FROM panel_entities").fetchone()[0]
        kinds = conn.execute(
            "SELECT COUNT(DISTINCT kind) FROM panel_entities").fetchone()[0]
        return CheckResult("database", "ok",
                           f"{ents} entidade(s), {kinds} kind(s)")
    finally:
        conn.close()


def check_join() -> CheckResult:
    core = os.path.join(REPO_ROOT, "core")
    links = []
    if os.path.isdir(core):
        for name in sorted(os.listdir(core)):
            p = os.path.join(core, name)
            if os.path.islink(p):
                links.append(("core/" + name, p))
    for sub in ("interfaces/cli", "interfaces/mcp"):
        d = os.path.join(REPO_ROOT, sub)
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                p = os.path.join(d, name)
                if os.path.islink(p):
                    links.append((f"{sub}/{name}", p))
    if not links:
        return CheckResult("join", "warn",
                           "nenhum symlink — modo standalone (sites reais "
                           "ausentes; veja README: Connecting real panels)")
    # os.path.exists segue o symlink: False = alvo ausente = quebrado
    quebrados = [nome for nome, p in links if not os.path.exists(p)]
    if quebrados:
        return CheckResult("join", "fail",
                           f"symlinks quebrados: {', '.join(quebrados)} "
                           "(rode ./join.sh no repo privado)")
    return CheckResult("join", "ok", f"{len(links)} symlink(s) íntegro(s)")


def _session_files() -> list[str]:
    raiz = REPO_ROOT
    arq = sorted(f for f in os.listdir(raiz) if f.endswith("_session.json"))
    return arq


def check_sessions(now: _dt.datetime | None = None) -> list[CheckResult]:
    now = now or _dt.datetime.now()
    resultados = []
    arquivos = _session_files()
    if not arquivos:
        return [CheckResult("sessions", "warn",
                            "nenhum *_session.json — rode <site>-login --save")]
    for f in arquivos:
        path = os.path.join(REPO_ROOT, f)
        site = f[: -len("_session.json")]
        try:
            import json
            sess = json.loads(open(path, encoding="utf-8").read())
            tem_token = bool(sess.get("token"))
        except (OSError, ValueError):
            resultados.append(CheckResult(f"session:{site}", "fail",
                                          "arquivo corrupto/ilegível"))
            continue
        idade_d = (now - _dt.datetime.fromtimestamp(
            os.path.getmtime(path))).total_seconds() / 86400
        if not tem_token:
            resultados.append(CheckResult(f"session:{site}", "fail",
                                          "sem token no arquivo"))
        elif idade_d > _SESSION_OLD_DAYS:
            resultados.append(CheckResult(f"session:{site}", "fail",
                                          f"{idade_d:.0f} dias — provavelmente "
                                          "expirada; relogue"))
        elif idade_d > _SESSION_FRESH_DAYS:
            resultados.append(CheckResult(f"session:{site}", "warn",
                                          f"{idade_d:.0f} dias — validar com "
                                          f"{site}-status"))
        else:
            resultados.append(CheckResult(f"session:{site}", "ok",
                                          f"{idade_d:.1f} dia(s)"))
    return resultados


def check_env() -> list[CheckResult]:
    resultados = []
    if os.environ.get("SIGMA_ALLOW_DESTRUCTIVE") == "1":
        resultados.append(CheckResult(
            "env:destructive", "fail",
            "SIGMA_ALLOW_DESTRUCTIVE=1 — GATE DESTRUTIVO ABERTO "
            "(desligue se não for executar escrita aprovada)"))
    else:
        resultados.append(CheckResult("env:destructive", "ok",
                                      "gate destrutivo fechado"))
    display = os.environ.get("HUB_DISPLAY", "virtual")
    if display in ("virtual", "headless", "x11"):
        resultados.append(CheckResult("env:display", "ok", f"HUB_DISPLAY={display}"))
    else:
        resultados.append(CheckResult(
            "env:display", "warn",
            f"HUB_DISPLAY={display!r} inválido (virtual|headless|x11)"))
    if os.environ.get("SIGMA_PROXY"):
        resultados.append(CheckResult("env:proxy", "ok",
                                      "SIGMA_PROXY setado (valor oculto)"))
    return resultados


def check_deps() -> CheckResult:
    faltando = []
    for mod, uso in (("curl_cffi", "FAST_SYNC"),
                     ("openpyxl", "export xlsx"),
                     ("camoufox", "browser"),
                     ("playwright", "browser"),
                     ("mcp", "servidor MCP")):
        try:
            __import__(mod)
        except ImportError:
            faltando.append(f"{mod} ({uso})")
    if faltando:
        return CheckResult("deps", "warn",
                           "ausentes: " + ", ".join(faltando)
                           + " — venv/bin/pip install " + " ".join(
                               f.split(" ")[0] for f in faltando))
    return CheckResult("deps", "ok",
                       "curl_cffi, openpyxl, camoufox, playwright, mcp")


# ---- sites (discovery genérico + probe GET opcional) --------------------------

def _site_packages() -> list[str]:
    import core
    nomes = []
    for m in pkgutil.iter_modules(core.__path__):
        if not m.ispkg or m.name in _BASE_MODULES:
            continue
        try:
            importlib.import_module(f"core.{m.name}.auth")
        except (ImportError, AttributeError):
            continue  # sem auth.py → não é site com sessão
        nomes.append(m.name)
    return sorted(nomes)


def _default_session_file(auth_mod) -> str | None:
    """Arquivo de sessão default do site, qualquer convenção:
    <SITE>_SESSION_FILE | SESSION_FILE | attr str *_session.json | cfg.session_file."""
    for attr in dir(auth_mod):
        val = getattr(auth_mod, attr)
        if isinstance(val, str) and val.endswith("_session.json") \
                and attr.upper().endswith(("SESSION_FILE",)):
            return val
    for holder in ("_CFG", "cfg"):
        cfg = getattr(auth_mod, holder, None)
        path = getattr(cfg, "session_file", None)
        if isinstance(path, str):
            return path
    return None


def _session_path_of(site: str, auth_mod) -> str | None:
    """Sessão ativa (multi-conta se houver); None se ausente.

    Fallback: o caminho que o módulo auth acredita pode apontar pro repo
    PRIVADO (join via symlink resolve __file__ lá) enquanto o arquivo real
    ficou no root deste hub (padrão legado pré-refactor) — nesse caso usa
    o arquivo do root, que é onde os comandos do hub o encontrariam.
    """
    resolved = None
    try:
        contas = auth_mod.load_accounts()
        if contas and hasattr(auth_mod, "resolve_active_account"):
            ativa = auth_mod.resolve_active_account(contas)
            if ativa and hasattr(auth_mod, "session_path_for"):
                resolved = auth_mod.session_path_for(ativa["username"], contas)
    except Exception:
        pass  # site sem multi-conta — cai no default
    resolved = resolved or _default_session_file(auth_mod)
    if resolved and not os.path.exists(resolved):
        legado = os.path.join(REPO_ROOT, f"{site}_session.json")
        if os.path.exists(legado):
            return legado
    return resolved


def check_site_session(site: str, auth_mod) -> CheckResult:
    path = _session_path_of(site, auth_mod)
    if not path or not os.path.exists(path):
        return CheckResult(f"site:{site}", "warn",
                           f"sem sessão salva — rode {site}-login --save")
    idade_d = (_dt.datetime.now() - _dt.datetime.fromtimestamp(
        os.path.getmtime(path))).total_seconds() / 86400
    import json
    try:
        sess = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return CheckResult(f"site:{site}", "fail", "session.json corrupto")
    if not sess.get("token"):
        return CheckResult(f"site:{site}", "fail", "sessão sem token")
    status = "ok" if idade_d <= _SESSION_FRESH_DAYS else (
        "warn" if idade_d <= _SESSION_OLD_DAYS else "fail")
    return CheckResult(f"site:{site}", status,
                       f"sessão com {idade_d:.1f} dia(s)")


def check_site_net(site: str, auth_mod) -> CheckResult:
    """Healthcheck GET puro (/auth/me) — um request, sem retry em CF."""
    path = _session_path_of(site, auth_mod)
    if not path or not os.path.exists(path):
        return CheckResult(f"net:{site}", "warn", "sem sessão — probe pulado")
    try:
        api_mod = importlib.import_module(f"core.{site}.api")
    except ImportError:
        return CheckResult(f"net:{site}", "ok",
                           "sessão ok (probe não aplicável — site não-sigma)")
    cls = None
    for _, obj in inspect.getmembers(api_mod, inspect.isclass):
        if issubclass(obj, _panel_client()) and obj is not _panel_client() \
                and getattr(obj, "API_BASE", ""):
            cls = obj
            break
    if cls is None:
        return CheckResult(f"net:{site}", "ok",
                           "sessão ok (sem PanelApiClient — probe pulado)")
    import json
    sess = json.loads(open(path, encoding="utf-8").read())
    try:
        client = cls(token=sess["token"],
                     transport=_probe_transport(sess))
        resp = client._request("/auth/me")
        status = resp.status_code
    except CloudflareBlocked:
        return _probe_via_browser(site, cls, path)
    except Exception as e:  # rede morta, DoH falhou etc.
        return CheckResult(f"net:{site}", "fail", f"GET /auth/me falhou: {e}")
    if status == 200:
        motor = "curl_cffi" if _HAS_CURL_CFFI else "requests"
        return CheckResult(f"net:{site}", "ok", f"GET /auth/me → 200 ({motor})")
    if status in (403, 429):
        return _probe_via_browser(site, cls, path)
    return CheckResult(f"net:{site}", "fail", f"GET /auth/me → {status}")


def _probe_via_browser(site: str, cls, session_path: str) -> CheckResult:
    """CF barrou o transporte HTTP — 1 fetch GET no browser real, guard on.

    NÃO usa ensure_logged_page (exigiria credenciais e poderia disparar
    login — regra 6: sem brute-force). Restaura os cookies da sessão salva
    no contexto, aguarda challenge de CF (regra 4: esperar, não falhar),
    instala o guard e faz UM fetch GET /auth/me. Veredito honesto:
    200 verde · 401 token morto · 403/429 mesmo no browser = IP bloqueado
    (aguardar/proxy/relogin — nada a fazer daqui, NÃO insistir).
    """
    import json as _json
    from urllib.parse import urlparse

    try:
        sess = _json.loads(open(session_path, encoding="utf-8").read())
        if not sess.get("token"):
            return CheckResult(f"net:{site}", "fail", "sessão sem token")
        from core.browser import BrowserEngine, is_cf_challenge
        from core.guard import install_guard
        from core.panel_api import _AXIOS_HEADERS, _BrowserTransport

        origin = (f"{urlparse(cls.API_BASE).scheme}://"
                  f"{urlparse(cls.API_BASE).hostname}")
        with BrowserEngine.get_page() as page:
            ctx = page.context
            ctx.clear_cookies()
            cookies = [c for c in sess.get("cookies", [])
                       if c.get("name") and c.get("value")]
            if cookies:
                ctx.add_cookies(cookies)
            page.goto(origin, timeout=60_000)
            for _ in range(12):  # ~60s: CF challenge pode levar ~10s+
                if not is_cf_challenge(page):
                    break
                page.wait_for_timeout(5_000)
            bloqueado = is_cf_challenge(page)
            install_guard(page)  # kill switch: só GET passa daqui
            transport = _BrowserTransport(page, extra_headers=_AXIOS_HEADERS)
            r = transport.get(f"{cls.API_BASE}/auth/me",
                              headers={"Authorization":
                                       f"Bearer {sess['token']}"})
        if r.status_code == 200:
            return CheckResult(f"net:{site}", "ok",
                               "GET /auth/me → 200 (browser — CF barrou o "
                               "HTTP direto)")
        if bloqueado:
            return CheckResult(
                f"net:{site}", "warn",
                f"CF bloqueou até o browser ({r.status_code}; 'Attention "
                "Required' = IP bloqueado) — aguardar/proxy/relogin; "
                "validade do token indefinível daqui")
        if r.status_code == 401:
            return CheckResult(f"net:{site}", "fail",
                               "token inválido (401) — sessão morta, relogue")
        if r.status_code in (403, 429):
            return CheckResult(f"net:{site}", "warn",
                               f"HTTP {r.status_code} — sessão/clarence "
                               "vencida; relogue")
        return CheckResult(f"net:{site}", "fail",
                           f"GET /auth/me → {r.status_code} (browser)")
    except Exception as e:
        return CheckResult(f"net:{site}", "fail",
                           f"probe browser falhou: {e}")


try:
    import curl_cffi  # noqa: F401
    _HAS_CURL_CFFI = True
except ImportError:
    _HAS_CURL_CFFI = False


def _probe_transport(sess: dict):
    """Transporte do healthcheck: FAST_SYNC (curl_cffi, mesmo do sync) se
    houver; requests puro como fallback (CF pode barrar → warn, não retry)."""
    if _HAS_CURL_CFFI:
        from core.panel_api import _AXIOS_HEADERS, _HttpTransport
        return _HttpTransport(sess["token"], sess.get("cookies") or [],
                              extra_headers=_AXIOS_HEADERS)
    return None


def _panel_client():
    from core.panel_api import PanelApiClient
    return PanelApiClient


# ---- orquestração --------------------------------------------------------------

def run_checks(with_net: bool = False,
               now: _dt.datetime | None = None) -> list[CheckResult]:
    """Todos os checks em ordem; `net` adiciona o probe GET por site."""
    resultados = [check_python(), check_database(), check_join()]
    resultados += check_sessions(now)
    resultados += check_env()
    resultados.append(check_deps())
    if with_net:
        for site in _site_packages():
            auth_mod = importlib.import_module(f"core.{site}.auth")
            resultados.append(check_site_session(site, auth_mod))
            resultados.append(check_site_net(site, auth_mod))
    return resultados
