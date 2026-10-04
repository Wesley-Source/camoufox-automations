"""Auth do painel blackbr (painelblackbr.com).

Máquina comum (sessão 0600 atômica, multi-conta, validação ativa de sessão,
failover) vive em core/panel_auth.py — regra do AGENTS.md: correção vai no
BASE, não nas cópias. Aqui ficam só: constantes públicas do site, o hook
_login_flow (genérico multi-seletor — vendor não-sigma) e os re-exports
usados por CLI/MCP.
"""
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from core.panel_auth import SiteConfig
from core import panel_auth as _base

BLACKBR_URL = "https://painelblackbr.com"
BLACKBR_API = BLACKBR_URL + "/api"
_BODY_SNIPPET = 4000  # ponytail: guardamos só um trecho de cada response no log
BLACKBR_SESSION_FILE = str(Path(__file__).resolve().parents[2] / "blackbr_session.json")
BLACKBR_ACCOUNTS_FILE = str(Path(__file__).resolve().parents[2] / "blackbr_accounts.json")
BLACKBR_LAST_GOOD_FILE = str(Path(__file__).resolve().parents[2] / ".blackbr_last_good")  # CR-25
_VALIDATE_SETTLE = 8  # ponytail: janela p/ o SPA devolver 401 ou redirecionar
_LOGIN_FORM_TIMEOUT = 20_000  # Hermes G2/G6: CF levou ~10s ao vivo; 8s falhou intermitente

_CFG = SiteConfig(
    name="blackbr",
    url=BLACKBR_URL,
    module=sys.modules[__name__],
    session_attr="BLACKBR_SESSION_FILE",
    accounts_attr="BLACKBR_ACCOUNTS_FILE",
    last_good_attr="BLACKBR_LAST_GOOD_FILE",
    monitor_scope="host",
)


def _login_flow(page, username: str, password: str, captured: list):
    page.goto(BLACKBR_URL, wait_until="domcontentloaded", timeout=60_000)
    # Hermes G4: challenge do CF = esperar, não "form nao encontrado".
    for _ in range(6):
        from core.browser import is_cf_challenge  # lazy: tests offline não pagam camoufox/playwright
        if not is_cf_challenge(page):
            break
        time.sleep(5)
    # Vendor desconhecido (NÃO é sigma.st): não assumimos seletores do Sigma.
    # Aceitamos os padrões mais comuns de form; se nada renderizar, dumpamos
    # o DOM em out/ e adaptamos com evidência (mesma tática que revelou o
    # login v3.94 do woodcine).
    user_sel = None
    for sel in ("input[name=username]", "input[name=email]",
                "input[type=email]", "input[type=text]"):
        try:
            page.wait_for_selector(sel, timeout=_LOGIN_FORM_TIMEOUT, state="visible")
            user_sel = sel
            break
        except Exception:
            continue
    if not user_sel:
        outdir = Path("core/blackbr/explore/out")
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "login_dom.html").write_text(page.content(), encoding="utf-8")
        raise RuntimeError(
            "Form de login do blackbr não encontrado. DOM salvo em "
            "core/blackbr/explore/out/login_dom.html — adapte _login_flow "
            "com o seletor real."
        )
    page.fill(user_sel, username)
    try:
        page.wait_for_selector("input[type=password]", timeout=_LOGIN_FORM_TIMEOUT, state="visible")
    except Exception:
        # Painel estilo v3.94: tile "última conta" antes do campo de senha.
        btn = page.locator(f"button:has-text('{username}')").first
        btn.wait_for(state="visible", timeout=30_000)
        btn.click()
    page.wait_for_selector("input[type=password]", timeout=120_000)
    page.fill("input[type=password]", password)
    try:
        page.click("#kt_sign_in_submit", timeout=3_000)
    except Exception:
        try:
            page.click("button[type=submit]", timeout=3_000)
        except Exception:
            page.press("input[type=password]", "Enter")

    # Sucesso = token no localStorage OU a URL sai da página de login.
    try:
        page.wait_for_function(
            "() => !!localStorage.getItem('token')", timeout=60_000
        )
    except Exception:
        if "login" not in page.url and "sign" not in page.url:
            return  # SPA sem token no localStorage — URL já saiu do login
        login_resp = next(
            (c for c in reversed(captured) if "/login" in c["url"]), None
        )
        detail = login_resp["response_body"] if login_resp else "sem resposta capturada"
        raise RuntimeError(f"Login blackbr falhou. Resposta: {detail}")


# Wrappers `def` — superfície pública idêntica à de antes do refactor
# (CLI/MCP/testes continuam importando os mesmos nomes; late binding via
# _CFG.module mantém monkeypatch funcionando).
def _attach_api_monitor(page, captured: list):
    return _base.attach_api_monitor(_CFG, page, captured)

def load_session(path: str = None) -> dict | None:
    return _base.load_session(_CFG, path)

def save_session(sess: dict, path: str = None, username: str = None) -> None:
    return _base.save_session(_CFG, sess, path, username)

def load_accounts(path: str = None) -> list:
    return _base.load_accounts(_CFG, path)

def session_path_for(username: str | None, accounts: list | None = None) -> str:
    return _base.session_path_for(_CFG, username, accounts)

def _read_last_good(path: str = None) -> str | None:
    return _base.read_last_good(_CFG, path)

def set_last_good(username: str, path: str = None) -> None:
    return _base.set_last_good(_CFG, username, path)

def resolve_active_account(accounts: list | None = None) -> dict | None:
    return _base.resolve_active_account(_CFG, accounts)

def _restore_session(page, session: dict) -> None:
    return _base.restore_session(_CFG, page, session)

def _session_still_valid(page, captured: list, token: str = "") -> bool:
    return _base.session_still_valid(_CFG, page, captured, token)

@contextmanager
def _ensure_multi(accounts: list, active: dict, proxy: str = None, guard=None):
    with _base._ensure_multi(_CFG, accounts, active, proxy, guard) as s:
        yield s

@contextmanager
def ensure_logged_page(username: str = None, password: str = None, proxy: str = None,
                       guard=None, session_path: str = None):
    with _base.ensure_logged_page(_CFG, username, password, proxy, guard, session_path) as s:
        yield s

def default_proxy() -> str | None:
    return _base.default_proxy(_CFG)

def allow_destructive() -> bool:
    return _base.allow_destructive(_CFG)

@contextmanager
def logged_page(username: str, password: str, proxy: str = None, guard=None):
    with _base.logged_page(_CFG, username, password, proxy, guard) as s:
        yield s

def login(username: str, password: str, proxy: str = None) -> dict:
    return _base.login(_CFG, username, password, proxy)
