"""Auth do painel Woodcine (woodcine.sigma.st).

Máquina comum (sessão 0600 atômica, multi-conta, validação ativa de sessão,
failover) vive em core/panel_auth.py — regra do AGENTS.md: correção vai no
BASE, não nas cópias. Aqui ficam só: constantes públicas do site, o hook
_login_flow (tile "última conta" do v3.94) e os re-exports usados por CLI/MCP.
"""
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from core.browser import BrowserEngine, is_cf_challenge
from core.panel_auth import SiteConfig
from core import panel_auth as _base

WOODCINE_URL = "https://woodcine.sigma.st"
WOODCINE_API = WOODCINE_URL + "/api"
_BODY_SNIPPET = 4000  # ponytail: guardamos só um trecho de cada response no log
WOODCINE_SESSION_FILE = str(Path(__file__).resolve().parents[2] / "woodcine_session.json")
WOODCINE_ACCOUNTS_FILE = str(Path(__file__).resolve().parents[2] / "woodcine_accounts.json")
WOODCINE_LAST_GOOD_FILE = str(Path(__file__).resolve().parents[2] / ".woodcine_last_good")  # CR-25
_VALIDATE_SETTLE = 8  # ponytail: janela p/ o SPA devolver 401 ou redirecionar
_LOGIN_FORM_TIMEOUT = 30_000  # Hermes G2/G6: CF pode levar ~10s; v3.94 borderline em 20s

_CFG = SiteConfig(
    name="woodcine",
    url=WOODCINE_URL,
    module=sys.modules[__name__],
    session_attr="WOODCINE_SESSION_FILE",
    accounts_attr="WOODCINE_ACCOUNTS_FILE",
    last_good_attr="WOODCINE_LAST_GOOD_FILE",
    monitor_scope="/api",
)


def _login_flow(page, username: str, password: str, captured: list):
    page.goto(WOODCINE_URL, wait_until="domcontentloaded", timeout=60_000)
    # Hermes G4: challenge do CF = esperar, não "form nao encontrado".
    for _ in range(6):
        if not is_cf_challenge(page):
            break
        time.sleep(5)
    # O form do SPA demora a renderizar — espera explícita, sem sleep fixo.
    # v3.94 (FOX SERVERS): quando há uma conta recente, o painel mostra tela
    # de confirmação ("{username} Último uso") sem nenhum form; clicar no
    # botão da conta revela o campo de senha.
    try:
        page.wait_for_selector("input[name=username]", timeout=_LOGIN_FORM_TIMEOUT)
    except Exception:
        btn = page.locator(f"button:has-text('{username}')").first
        btn.wait_for(state="visible", timeout=60_000)
        btn.click()
    page.wait_for_selector("input[name=password]", timeout=120_000)
    page.fill("input[name=password]", password)
    try:
        page.click("#kt_sign_in_submit", timeout=5_000)
    except Exception:
        # Tela nova pode não ter o id — Enter no campo de senha submete.
        page.press("input[name=password]", "Enter")

    # Sucesso = token no localStorage. O FOX v3.94 pode navegar destruindo o
    # contexto JS e o monitor nem sempre captura o POST — o token no
    # localStorage é a única fonte da verdade (nunca a resposta capturada).
    deadline = time.time() + 90
    token_ok = False
    while time.time() < deadline:
        try:
            if page.evaluate("() => localStorage.getItem('token')"):
                token_ok = True
                break
        except Exception:
            pass  # contexto destruído por navegação — retry
        time.sleep(2)
    if not token_ok:
        raise RuntimeError(
            "Login woodcine falhou: token não apareceu no localStorage em 90s."
        )


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
