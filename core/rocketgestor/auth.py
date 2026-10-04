"""
Auth do Rocket Gestor (app.rocketgestor.com) — 5º site do hub, família PRÓPRIA.

Diferente dos 4 painéis Sigma (SPA + Bearer em localStorage): o Rocket é
Django server-rendered — login por form POST com csrfmiddlewaretoken e
sessão = COOKIES (sessionid/csrftoken). Nada de localStorage/Bearer/DoH.

Política do painel (decisão do dono): SEM sistema de créditos — liberado
criar/alterar/deletar CLIENTES DE TESTE (zz_test_*) à vontade; clientes
REAIS intocados sem aprovação explícita.

Login sem brute-force: tentativa errada pode gerar bloqueio; só tenta com
credencial confirmada (accounts file 0600).
"""
import fcntl
import json
import os
import time
from pathlib import Path

from core.browser import BrowserEngine, is_cf_challenge
from core.guard import install_guard

ROCKET_URL = "https://app.rocketgestor.com"
LOGIN_PATH = "/accounts/login/"

ROOT = Path(__file__).resolve().parents[2]
ROCKET_ACCOUNTS_FILE = str(ROOT / "rocketgestor_accounts.json")
ROCKET_SESSION_FILE = str(ROOT / "rocketgestor_session.json")
ROCKET_LAST_GOOD_FILE = str(ROOT / ".rocketgestor_last_good")
_LOGIN_FORM_TIMEOUT = 30_000


def load_accounts(path: str = None) -> list:
    """Contas do arquivo (lista de dicts). Sem arquivo/env = []."""
    path = path or ROCKET_ACCOUNTS_FILE
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_last_good(username: str) -> None:
    fd = os.open(ROCKET_LAST_GOOD_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(username)


def resolve_active_account(accounts: list) -> dict | None:
    """SIGMA_ACCOUNT > ponteiro .rocketgestor_last_good > primeira do arquivo."""
    env_user = os.environ.get("SIGMA_ACCOUNT")
    if env_user:
        for a in accounts:
            if a["username"] == env_user:
                return a
    if accounts:
        try:
            last = Path(ROCKET_LAST_GOOD_FILE).read_text().strip()
            for a in accounts:
                if a["username"] == last:
                    return a
        except Exception:
            pass
        return accounts[0]
    return None


def save_session(page, path: str = None, username: str = None) -> None:
    """Sessão Django = cookies do contexto (sessionid/csrftoken)."""
    path = path or ROCKET_SESSION_FILE
    data = {"site": "rocketgestor", "username": username,
            "cookies": page.context.cookies(ROCKET_URL), "saved_at": time.time()}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_session(path: str = None) -> dict | None:
    """Sessão válida = tem cookies (Django é cookie-only)."""
    path = path or ROCKET_SESSION_FILE
    try:
        s = json.loads(Path(path).read_text(encoding="utf-8"))
        return s if s.get("cookies") else None
    except Exception:
        return None


def _restore_cookies(page, sess: dict) -> None:
    try:
        page.context.add_cookies(sess.get("cookies") or [])
    except Exception:
        pass


def _logged_in(page) -> bool:
    """Na área autenticada? Checa URL + fetch ativo do dashboard (G3):
    sessão morta redireciona o fetch para o login (status 0 no manual)."""
    try:
        if "/accounts/login" in (page.url or ""):
            return False
        return page.evaluate(
            "fetch('/gerenciador/dashboard/', {redirect:'manual'})"
            ".then(r => r.status === 200)"
        )
    except Exception:
        return False


def _fill_login(page, username: str, password: str) -> None:
    """Form Django: csrfmiddlewaretoken vai no submit nativo do browser."""
    page.wait_for_selector("#login-form input[name=username]",
                           timeout=_LOGIN_FORM_TIMEOUT)
    page.fill("#login-form input[name=username]", username)
    page.fill("#login-form input[name=password]", password)
    page.click("#login-form button[type=submit], #login-form input[type=submit]")


class Session:
    """Superfície compatível com os exploradores dos painéis sigma
    (s.page/s.captured/s.blocked/s.session_path/s.account)."""

    def __init__(self, page, session_path: str, account: str):
        self.page = page
        self.session_path = session_path
        self.account = account
        self.captured: list = []
        self.blocked: list = []

    @property
    def token(self) -> str:
        # Django não tem Bearer — "token" aqui é o marcador de sessão
        return f"cookies:{len(self.page.context.cookies(ROCKET_URL))}"


def ensure_logged_page(session_path: str = None, proxy: str = None, guard=None):
    """Context manager: devolve Session com page logado no Rocket (sessão
    reutilizada se válida, senão login fresco 1x). Guard instalado DEPOIS
    do login (não bloquear o POST de autenticação). Captura passiva de
    responses (monitor_scope=host — Django não tem prefixo /api garantido)."""
    import contextlib

    @contextlib.contextmanager
    def _cm():
        accounts = load_accounts()
        active = resolve_active_account(accounts)
        if not active:
            raise RuntimeError(
                "Sem conta Rocket Gestor. Cadastre: rocketgestor_accounts.json "
                '[{"username": "...", "password": "..."}] (0600)'
            )
        sess = load_session(session_path)
        with BrowserEngine.get_page(proxy=proxy) as page:
            s = Session(page, session_path or ROCKET_SESSION_FILE,
                        active["username"])
            page.on("response", lambda r: s.captured.append(
                {"method": r.request.method, "url": r.url,
                 "status": r.status}) if r.url.startswith(ROCKET_URL) else None)
            if sess:
                _restore_cookies(page, sess)
                page.goto(ROCKET_URL + "/", wait_until="domcontentloaded",
                          timeout=60_000)
                for _ in range(6):  # G4: CF = esperar, não falhar
                    if not is_cf_challenge(page):
                        break
                    time.sleep(5)
                if _logged_in(page):
                    if guard:
                        s.blocked = guard(page)
                    yield s
                    return
            # M6: serializa relogin entre processos (cron + MCP simultâneos
            # não abrem dois logins Django na mesma conta).
            lock = Path(session_path or ROCKET_SESSION_FILE).with_suffix(".lock")
            with open(lock, "w") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)  # bloqueante; ok p/ 2-3 processos
                # Login fresco (1 tentativa, credencial confirmada)
                page.goto(ROCKET_URL + LOGIN_PATH, wait_until="domcontentloaded",
                          timeout=60_000)
                for _ in range(6):
                    if not is_cf_challenge(page):
                        break
                    time.sleep(5)
                _fill_login(page, active["username"], active["password"])
                # Django redirecta pós-login; espera sair do /accounts/login
                deadline = time.time() + 60
                while time.time() < deadline:
                    try:
                        if _logged_in(page):
                            break
                    except Exception:
                        pass
                    time.sleep(2)
                else:
                    raise RuntimeError(
                        f"Login rocketgestor falhou para {active['username']} "
                        "(credencial ou CF). NÃO repita sem confirmar a senha."
                    )
                save_session(page, session_path, username=active["username"])
                _write_last_good(active["username"])
            if guard:
                s.blocked = guard(page)
            yield s

    return _cm()


def default_proxy() -> str | None:
    return os.environ.get("SIGMA_PROXY")
