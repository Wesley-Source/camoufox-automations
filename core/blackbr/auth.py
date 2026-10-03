"""
Scraper do painel blackbr (https://painelblackbr.com).

Fluxo de auth descoberto via recon do bundle JS (assets/ApiService-*.js):
- Login: POST /api/auth/login  {username, password}
- Token: salvo em localStorage["token"], enviado depois como "Authorization: Bearer <token>"
- Bloqueio Cloudflare: resposta do login vem como página HTML (cf-footer-ip / Ray ID)

O login é feito via navegador (Camoufox) para passar no Cloudflare e capturar
o cf_clearance; ao final devolvemos token + cookies + log de requests /api/*.
"""
import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import typer

from core.browser import BrowserEngine, is_cf_challenge

BLACKBR_URL = "https://painelblackbr.com"
BLACKBR_API = BLACKBR_URL + "/api"
_BODY_SNIPPET = 4000  # ponytail: guardamos só um trecho de cada response no log
BLACKBR_SESSION_FILE = str(Path(__file__).resolve().parents[2] / "blackbr_session.json")
BLACKBR_ACCOUNTS_FILE = str(Path(__file__).resolve().parents[2] / "blackbr_accounts.json")
BLACKBR_LAST_GOOD_FILE = str(Path(__file__).resolve().parents[2] / ".blackbr_last_good")  # CR-25
_VALIDATE_SETTLE = 8  # ponytail: janela p/ o SPA devolver 401 ou redirecionar; subir se o painel ficar mais lento
_LOGIN_FORM_TIMEOUT = 20_000  # Hermes G2/G6: CF levou ~10s ao vivo; 8s falhou intermitente


def _attach_api_monitor(page, captured: list):
    """Captura toda request/response do HOST do painel (API base desconhecida
    — vendor diferente de sigma.st; pode nem usar /api). Corpos capados em
    _BODY_SNIPPET para o log não explodir."""

    host = BLACKBR_URL.replace("https://", "")

    def on_response(resp):
        try:
            if host not in resp.url:
                return
            body = ""
            try:
                body = resp.text()[:_BODY_SNIPPET]
            except Exception:
                pass
            post = resp.request.post_data
            # A2: qualquer corpo com senha não vai pro log (login, create, etc.)
            if post and "password" in post.lower():
                post = "[REDACTED]"
            captured.append({
                "method": resp.request.method,
                "url": resp.url,
                "status": resp.status,
                "post_data": post,
                "response_body": body,
            })
        except Exception:
            pass  # monitor nunca derruba o fluxo principal

    page.on("response", on_response)


def _login_flow(page, username: str, password: str, captured: list):
    page.goto(BLACKBR_URL, wait_until="domcontentloaded", timeout=60_000)
    # Hermes G4: challenge do CF = esperar, não "form nao encontrado".
    for _ in range(6):
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


def load_session(path: str = BLACKBR_SESSION_FILE) -> dict | None:
    """Sessão salva (token+cookies) ou None se ausente/corrompida/incompleta."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return s if s.get("token") and s.get("cookies") else None


def save_session(sess: dict, path: str = BLACKBR_SESSION_FILE, username: str = None) -> None:
    """CR-12: 0600 + troca atômica — token+cookies nunca ficam legíveis para
    grupo/outros nem pela metade escritos. M3: tmp por-pid (duas corridas
    não se truncam) e arquivo nasce 0600 (sem janela write→chmod)."""
    if username:
        sess = {**sess, "username": username}
    p = Path(path)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(sess, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


# ---- multi-conta -----------------------------------------------------------

def load_accounts(path: str = None) -> list:
    """[{username, password}] de blackbr_accounts.json + env (env entra como
    primeira entrada se ainda não estiver no arquivo). Ordem = prioridade.
    path=None resolve BLACKBR_ACCOUNTS_FILE na chamada (testável via monkeypatch)."""
    path = path or BLACKBR_ACCOUNTS_FILE
    """Contas cadastradas [{username, password}] — ordem do arquivo = prioridade.

    SIGMA_USERNAME/SIGMA_PASSWORD (quando setados e ainda não presentes)
    entram como PRIMEIRA entrada — compat com o modo antigo. Arquivo
    ausente/corrompido = só env. Lista vazia = modo single-account legado.
    """
    accounts: list = []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw, list):
            for a in raw:
                if isinstance(a, dict) and a.get("username") and a.get("password"):
                    accounts.append({"username": a["username"], "password": a["password"]})
    except Exception:
        pass
    env_u = os.environ.get("SIGMA_USERNAME")
    env_p = os.environ.get("SIGMA_PASSWORD")
    if env_u and env_p and not any(a["username"] == env_u for a in accounts):
        accounts.insert(0, {"username": env_u, "password": env_p})
    return accounts


def session_path_for(username: str | None, accounts: list | None = None) -> str:
    """Sessão da conta PRIMÁRIA continua em BLACKBR_SESSION_FILE (zero migração);
    as demais viram dotfiles .blackbr_session_<usuario>.json."""
    if not username:
        return BLACKBR_SESSION_FILE
    accounts = accounts if accounts is not None else load_accounts()
    if accounts and username == accounts[0]["username"]:
        return BLACKBR_SESSION_FILE
    return str(Path(BLACKBR_SESSION_FILE).parent / f".blackbr_session_{username}.json")


def _read_last_good(path: str = None) -> str | None:
    path = path or BLACKBR_LAST_GOOD_FILE
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def set_last_good(username: str, path: str = None) -> None:
    path = path or BLACKBR_LAST_GOOD_FILE
    """Ponteiro da conta ativa — fonte de verdade compartilhada por CLI e MCP."""
    try:
        Path(path).write_text(username + "\n", encoding="utf-8")
    except Exception:
        pass


def resolve_active_account(accounts: list | None = None) -> dict | None:
    """SIGMA_ACCOUNT (override por processo, não toca o ponteiro)
    > ponteiro .blackbr_last_good > primeira conta. None = modo legado."""
    accounts = accounts if accounts is not None else load_accounts()
    if not accounts:
        return None
    by_name = {a["username"]: a for a in accounts}
    env_pick = os.environ.get("SIGMA_ACCOUNT")
    if env_pick and env_pick in by_name:
        return by_name[env_pick]
    last_good = _read_last_good()
    if last_good and last_good in by_name:
        return by_name[last_good]
    return accounts[0]


def _restore_session(page, session: dict) -> None:
    """Injeta cookies (cf_clearance incluído) + localStorage ANTES do SPA carregar."""
    page.context.add_cookies(session["cookies"])
    storage = json.dumps(session.get("local_storage", {}))
    json.loads(storage)  # CR-18: só embute no JS se for JSON válido
    # add_init_script não aceita argumentos nesta versão do Playwright —
    # embutimos o JSON no corpo (dados nossos, validados acima; dumps com
    # ensure_ascii=True => ASCII puro, seguro como literal JS).
    page.add_init_script(
        "(() => { try { const d = " + storage + ";"
        " for (const [k, v] of Object.entries(d)) localStorage.setItem(k, v);"
        " } catch (e) {} })()"
    )


def _session_still_valid(page, captured: list, token: str = "") -> bool:
    """
    Validade em duas camadas: passiva (redireção pra login, form renderizado,
    401 do host) + cheque ATIVO /api/auth/me (Hermes G3 — a página de
    challenge do CF passa na passiva e daria falso positivo; /api/auth/me
    está provado 200 no probe da Fase 1).
    """
    try:
        page.goto(BLACKBR_URL, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(_VALIDATE_SETTLE)  # SPA usa websocket — networkidle nunca assenta
        url_lower = page.url.lower()
        if any(m in url_lower for m in ("login", "signin", "sign-in", "auth")):
            return False
        # Form de login renderizado = desautenticado, mesmo se a URL ainda não mudou.
        if page.locator("input[type=password]").count() > 0:
            return False
        host = BLACKBR_URL.replace("https://", "")
        if any(host in c["url"] and c["status"] == 401 for c in captured):
            return False
        # Cheque ativo: 401 aqui também é sessão morta, mesmo sem sinais passivos.
        status = page.evaluate(
            "async (t) => (await fetch('/api/auth/me',"
            " {headers: {Authorization: 'Bearer ' + t}})).status",
            token or "",
        )
        return status == 200
    except Exception as exc:
        # M7: erro de rede/transporte ≠ sessão morta. Propagar — relogar por
        # falha transitória desperdiça ~4min e mata uma sessão que estava boa.
        raise RuntimeError(f"Validação de sessão falhou (rede/proxy?): {exc}") from exc


@contextmanager
def _ensure_multi(accounts: list, active: dict, proxy: str = None, guard=None):
    """Multi-conta: tenta a sessão da ativa, depois das demais por prioridade
    (failover barato — só troca de arquivo). Todas mortas → relogin com a
    ATIVA apenas (sem cascata de relogin ~1min; senha morta se descobre uma
    vez e o erro é claro). Failover só no boot: round-robin por chamada
    churna cf_clearance e convida desafio do CF."""
    order = [active] + [a for a in accounts if a["username"] != active["username"]]
    # SIGMA_ACCOUNT é override por processo: não persiste no ponteiro global.
    from_env = os.environ.get("SIGMA_ACCOUNT") == active["username"]
    with BrowserEngine.get_page(proxy or default_proxy()) as page:
        captured: list = []
        _attach_api_monitor(page, captured)

        for cand in order:
            spath = session_path_for(cand["username"], accounts)
            saved = load_session(spath)
            if not saved:
                continue
            _restore_session(page, saved)
            if _session_still_valid(page, captured, saved["token"]):
                if not from_env:
                    set_last_good(cand["username"])
                blocked = guard(page) if guard else []
                typer.secho(f"✔ Sessão reutilizada ({cand['username']}).", fg=typer.colors.GREEN, err=True)
                yield SimpleNamespace(
                    page=page, token=saved["token"], captured=captured,
                    blocked=blocked, reused=True,
                    account=cand["username"], session_path=spath,
                )
                return

        spath = session_path_for(active["username"], accounts)
        lock = Path(spath).with_suffix(".lock")
        typer.secho(
            f"⚠ Nenhuma sessão válida — logando com {active['username']}...",
            fg=typer.colors.YELLOW, err=True,
        )
        # M3: serializa relogin entre processos (cron + MCP simultâneos).
        with open(lock, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)  # ponytail: bloqueante; ok p/ 2-3 processos
            _login_flow(page, active["username"], active["password"], captured)
            blocked = guard(page) if guard else []
            token = page.evaluate("() => localStorage.getItem('token')")
            save_session(
                {
                    "token": token,
                    "cookies": page.context.cookies(),
                    "local_storage": page.evaluate(
                        "() => Object.fromEntries(Object.entries(localStorage))"
                    ),
                },
                spath,
                username=active["username"],
            )
        if not from_env:
            set_last_good(active["username"])
        typer.secho(
            f"✔ Login completo ({active['username']}); sessão em {spath}.",
            fg=typer.colors.GREEN, err=True,
        )
        yield SimpleNamespace(
            page=page, token=token, captured=captured,
            blocked=blocked, reused=False,
            account=active["username"], session_path=spath,
        )


@contextmanager
def ensure_logged_page(username: str = None, password: str = None, proxy: str = None,
                       guard=None, session_path: str = BLACKBR_SESSION_FILE):
    """
    Como logged_page, mas reutiliza a sessão salva se ainda válida.

    MULTI-CONTA: se blackbr_accounts.json existir (ou env+arquivo combinados
    tiverem ≥1 conta), a resolução é SIGMA_ACCOUNT > ponteiro
    .blackbr_last_good > primeira conta; tenta a sessão de cada conta (ativa
    primeiro), reloga só na ativa se todas morarem e devolve
    .account/.session_path no yield. O parâmetro session_path é IGNORADO
    nesse modo (caminho vem de session_path_for).

    CR-03: single-launch — UM browser para toda a vida do contexto. Valida
    a sessão via fetch na própria página e, se morta, refaz o login NA
    MESMA página (validar via HTTP puro não é opção: CF bloqueia requests).
    Requer username/password ou env SIGMA_USERNAME/SIGMA_PASSWORD no caminho
    de relogin; atualiza o arquivo de sessão. .reused: bool.

    ponytail (CR-27): o guard entra após a verificação de validade — a
    janela de validação é só código nosso de leitura (goto + fetch GET);
    instalar guard antes abortaria POSTs do próprio SPA durante a validação
    e causaria falso negativo -> relogin desperdiçado.
    """
    accounts = load_accounts()
    if accounts:
        active = resolve_active_account(accounts)
        with _ensure_multi(accounts, active, proxy, guard) as s:
            yield s
        return

    username = username or os.environ.get("SIGMA_USERNAME")
    password = password or os.environ.get("SIGMA_PASSWORD")

    saved = load_session(session_path)

    with BrowserEngine.get_page(proxy or default_proxy()) as page:
        captured: list = []
        _attach_api_monitor(page, captured)

        reused = False
        if saved:
            _restore_session(page, saved)
            if _session_still_valid(page, captured, saved["token"]):
                reused = True

        if reused:
            blocked = guard(page) if guard else []
            typer.secho(f"✔ Sessão reutilizada ({session_path}).", fg=typer.colors.GREEN, err=True)
            token = saved["token"]
        else:
            if saved:
                typer.secho("⚠ Sessão salva inválida ou expirada — refazendo login...", fg=typer.colors.YELLOW, err=True)
            else:
                typer.secho(f"ℹ Sem sessão salva em {session_path} — logando...", fg=typer.colors.YELLOW, err=True)
            if not (username and password):
                raise RuntimeError(
                    "Sem sessão válida e sem credenciais. Defina SIGMA_USERNAME/SIGMA_PASSWORD "
                    "ou rode: venv/bin/python main.py blackbr-login --save"
                )
            # M3: serializa relogin entre processos (cron + MCP simultâneos
            # não abrem dois browsers/logins na mesma conta).
            lock = Path(session_path).with_suffix(".lock")
            with open(lock, "w") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)  # ponytail: bloqueante; ok p/ 2-3 processos
                _login_flow(page, username, password, captured)
                blocked = guard(page) if guard else []
                token = page.evaluate("() => localStorage.getItem('token')")
                save_session(
                    {
                        "token": token,
                        "cookies": page.context.cookies(),
                        "local_storage": page.evaluate(
                            "() => Object.fromEntries(Object.entries(localStorage))"
                        ),
                    },
                    session_path,
                )
            typer.secho(f"✔ Login completo; sessão atualizada em {session_path}.", fg=typer.colors.GREEN, err=True)

        yield SimpleNamespace(
            page=page, token=token, captured=captured,
            blocked=blocked, reused=reused,
            account=None, session_path=session_path,
        )


def default_proxy() -> str | None:
    """SIGMA_PROXY (ex.: socks5://100.x.y.z:1080 do microsocks no celular).

    ponytail: proxy cirúrgico — só o Sigma passa pelo caminho alternativo;
    todo o resto da máquina segue a rota normal.
    """
    return os.environ.get("SIGMA_PROXY") or None


def allow_destructive() -> bool:
    """CR-10: mutação destrutiva exige SIGMA_ALLOW_DESTRUCTIVE=1 no ambiente.

    'confirmar=True' preenchido pelo próprio LLM não é confirmação — o gate
    só abre com a variável setada por um humano.
    """
    return os.environ.get("SIGMA_ALLOW_DESTRUCTIVE") == "1"


@contextmanager
def logged_page(username: str, password: str, proxy: str = None, guard=None):
    """
    Contextmanager: abre o painel blackbr já logado e devolve
    SimpleNamespace(page, token, captured, blocked).

    `guard` é uma função f(page) -> lista de bloqueios; instalada APÓS o
    login (o POST de autenticação precisa passar). Use explore._guard
    para garantir modo somente-leitura.
    """
    if not username or not password:
        raise ValueError("username e password são obrigatórios")

    with BrowserEngine.get_page(proxy) as page:
        captured: list = []
        _attach_api_monitor(page, captured)
        _login_flow(page, username, password, captured)
        blocked = guard(page) if guard else []
        yield SimpleNamespace(
            page=page,
            token=page.evaluate("() => localStorage.getItem('token')"),
            captured=captured,
            blocked=blocked,
        )


def login(username: str, password: str, proxy: str = None) -> dict:
    """
    Faz login no painel blackbr e retorna a sessão.

    Retorna: {"token": str, "cookies": [...], "captured": [...], "local_storage": {...}}
    Levanta RuntimeError com o corpo da resposta se o login falhar.
    """
    with logged_page(username, password, proxy) as s:
        return {
            "token": s.token,
            "cookies": s.page.context.cookies(),
            "captured": s.captured,
            "local_storage": s.page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            ),
        }
