"""Base compartilhada de autenticação dos painéis (sigma, woodcine, blackbr).

Regra do AGENTS.md: correção vai no BASE, não nas cópias. Cada
`core/<site>/auth.py` mantém: constantes públicas do site, o hook
`_login_flow` (fluxo de login é a única divergência real de vendor) e
wrappers `def` que delegam pra cá.

LATE BINDING: as funções da base resolvem irmãos e constantes via
`cfg.module` (o módulo do site) EM TEMPO DE CHAMADA — monkeypatch nos
módulos dos sites continua funcionando como antes do refactor.
"""
import fcntl
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import typer

_BODY_SNIPPET = 4000  # ponytail: guardamos só um trecho de cada response no log


@dataclass(frozen=True)
class SiteConfig:
    """Config declarativa do site. Os ARQUIVOS e tempos resolvem via
    getattr(module, attr) a cada chamada — patchable pelos testes."""
    name: str                    # "sigma" | "woodcine" | "blackbr"
    url: str                     # ex.: https://lideriptv.sigma.st
    module: object               # módulo do site (late binding)
    session_attr: str            # nome da constante SESSION_FILE no módulo
    accounts_attr: str
    last_good_attr: str
    monitor_scope: str = "/api"  # "/api" ou "host" (vendor desconhecido)

    @property
    def api(self) -> str:
        return self.url + "/api"

    @property
    def host(self) -> str:
        return self.url.replace("https://", "")

    @property
    def session_file(self) -> str:
        return getattr(self.module, self.session_attr)

    @property
    def accounts_file(self) -> str:
        return getattr(self.module, self.accounts_attr)

    @property
    def last_good_file(self) -> str:
        return getattr(self.module, self.last_good_attr)

    @property
    def session_dot_prefix(self) -> str:
        return f".{self.name}_session_"

    @property
    def login_form_timeout(self) -> int:
        return getattr(self.module, "_LOGIN_FORM_TIMEOUT")

    @property
    def validate_settle(self) -> int:
        return getattr(self.module, "_VALIDATE_SETTLE")


def attach_api_monitor(cfg, page, captured: list):
    """Captura responses do painel para análise/debugging (corpo truncado)."""
    marker = cfg.host if cfg.monitor_scope == "host" else "/api"

    def on_response(resp):
        try:
            if marker not in resp.url:
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


def load_session(cfg, path: str = None) -> dict | None:
    """Sessão salva (token+cookies) ou None se ausente/corrompida/incompleta."""
    p = Path(path or cfg.session_file)
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    # Bearer-only panels (ex.: newmais) não setam cookies — token é a credencial.
    return s if s.get("token") else None


def save_session(cfg, sess: dict, path: str = None, username: str = None) -> None:
    """CR-12: 0600 + troca atômica — token+cookies nunca ficam legíveis para
    grupo/outros nem pela metade escritos. M3: tmp por-pid (duas corridas
    não se truncam) e arquivo nasce 0600 (sem janela write→chmod)."""
    if username:
        sess = {**sess, "username": username}
    p = Path(path or cfg.session_file)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(sess, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


# ---- multi-conta -----------------------------------------------------------


def load_accounts(cfg, path: str = None) -> list:
    """[{username, password}] de <site>_accounts.json + env (env entra como
    primeira entrada se ainda não estiver no arquivo). Ordem = prioridade.
    path=None resolve cfg.accounts_file na chamada (testável monkeypatch)."""
    path = path or cfg.accounts_file
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


def session_path_for(cfg, username: str | None, accounts: list | None = None) -> str:
    """Sessão da conta PRIMÁRIA continua no SESSION_FILE do site (zero
    migração); as demais viram dotfiles .<site>_session_<usuario>.json."""
    m = cfg.module
    if not username:
        return cfg.session_file
    accounts = accounts if accounts is not None else m.load_accounts()
    if accounts and username == accounts[0]["username"]:
        return cfg.session_file
    return str(Path(cfg.session_file).parent
               / f"{cfg.session_dot_prefix}{username}.json")


def read_last_good(cfg, path: str = None) -> str | None:
    path = path or cfg.last_good_file
    try:
        return Path(path).read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def set_last_good(cfg, username: str, path: str = None) -> None:
    path = path or cfg.last_good_file
    """Ponteiro da conta ativa — fonte de verdade compartilhada por CLI e MCP."""
    try:
        Path(path).write_text(username + "\n", encoding="utf-8")
    except Exception:
        pass


def resolve_active_account(cfg, accounts: list | None = None) -> dict | None:
    """SIGMA_ACCOUNT (override por processo, não toca o ponteiro)
    > ponteiro .<site>_last_good > primeira conta. None = modo legado."""
    m = cfg.module
    accounts = accounts if accounts is not None else m.load_accounts()
    if not accounts:
        return None
    by_name = {a["username"]: a for a in accounts}
    env_pick = os.environ.get("SIGMA_ACCOUNT")
    if env_pick and env_pick in by_name:
        return by_name[env_pick]
    last_good = m._read_last_good()
    if last_good and last_good in by_name:
        return by_name[last_good]
    return accounts[0]


def restore_session(cfg, page, session: dict) -> None:
    """Injeta cookies (cf_clearance incluído) + localStorage ANTES do SPA carregar."""
    page.context.add_cookies(session.get("cookies", []))
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


def session_still_valid(cfg, page, captured: list, token: str = "") -> bool:
    """
    Validade decidida pelo SERVIDOR: GET /api/auth/me com o token (200 = válido;
    Hermes G3 — challenge do CF passa na checagem passiva, só o cheque ativo
    pega o falso positivo). Complementos passivos: redireção pro login, form
    de login renderizado ou 401 em /api/* na janela de observação.
    """
    try:
        page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(cfg.validate_settle)  # SPA usa websocket — networkidle nunca assenta
        url_lower = page.url.lower()
        if any(mk in url_lower for mk in ("login", "signin", "sign-in", "auth")):
            return False
        # Form de login renderizado = desautenticado, mesmo se a URL ainda não mudou.
        if page.locator("input[type=password]").count() > 0:
            return False
        if any("/api" in c["url"] and c["status"] == 401 for c in captured):
            return False
        # Checagem ativa e determinística (GET, read-only).
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


# ---- contextmanagers -------------------------------------------------------


@contextmanager
def _ensure_multi(cfg, accounts: list, active: dict, proxy: str = None, guard=None):
    """Multi-conta: tenta a sessão da ativa, depois das demais por prioridade
    (failover barato — só troca de arquivo). Todas mortas → relogin com a
    ATIVA apenas (sem cascata de relogin ~1min; senha morta se descobre uma
    vez e o erro é claro). Failover só no boot: round-robin por chamada
    churna cf_clearance e convida desafio do CF."""
    m = cfg.module
    order = [active] + [a for a in accounts if a["username"] != active["username"]]
    # SIGMA_ACCOUNT é override por processo: não persiste no ponteiro global.
    from_env = os.environ.get("SIGMA_ACCOUNT") == active["username"]
    with m.BrowserEngine.get_page(proxy or m.default_proxy()) as page:
        captured: list = []
        m._attach_api_monitor(page, captured)

        for cand in order:
            spath = m.session_path_for(cand["username"], accounts)
            saved = m.load_session(spath)
            if not saved:
                continue
            m._restore_session(page, saved)
            if m._session_still_valid(page, captured, saved["token"]):
                if not from_env:
                    m.set_last_good(cand["username"])
                blocked = guard(page) if guard else []
                typer.secho(f"✔ Sessão reutilizada ({cand['username']}).", fg=typer.colors.GREEN, err=True)
                yield SimpleNamespace(
                    page=page, token=saved["token"], captured=captured,
                    blocked=blocked, reused=True,
                    account=cand["username"], session_path=spath,
                )
                return

        spath = m.session_path_for(active["username"], accounts)
        lock = Path(spath).with_suffix(".lock")
        typer.secho(
            f"⚠ Nenhuma sessão válida — logando com {active['username']}...",
            fg=typer.colors.YELLOW, err=True,
        )
        # M3: serializa relogin entre processos (cron + MCP simultâneos).
        with open(lock, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)  # ponytail: bloqueante; ok p/ 2-3 processos
            m._login_flow(page, active["username"], active["password"], captured)
            blocked = guard(page) if guard else []
            token = page.evaluate("() => localStorage.getItem('token')")
            m.save_session(
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
            m.set_last_good(active["username"])
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
def ensure_logged_page(cfg, username: str = None, password: str = None, proxy: str = None,
                       guard=None, session_path: str = None):
    """
    Como logged_page, mas reutiliza a sessão salva se ainda válida.

    MULTI-CONTA: se <site>_accounts.json existir, a resolução é
    SIGMA_ACCOUNT > ponteiro .<site>_last_good > primeira conta; tenta a
    sessão de cada conta (ativa primeiro), reloga só na ativa se todas
    morarem e devolve .account/.session_path no yield. session_path é
    IGNORADO nesse modo (caminho vem de session_path_for).

    CR-03: single-launch — UM browser para toda a vida do contexto. Valida
    a sessão via fetch na própria página e, se morta, refaz o login NA
    MESMA página (validar via HTTP puro não é opção: CF bloqueia requests).
    CR-27: o guard entra APÓS a validação (janela de validação é só leitura;
    guard antes abortaria POSTs do próprio SPA -> falso negativo).
    """
    m = cfg.module
    accounts = m.load_accounts()
    if accounts:
        active = m.resolve_active_account(accounts)
        with m._ensure_multi(accounts, active, proxy, guard) as s:
            yield s
        return

    session_path = session_path or cfg.session_file
    username = username or os.environ.get("SIGMA_USERNAME")
    password = password or os.environ.get("SIGMA_PASSWORD")

    saved = m.load_session(session_path)

    with m.BrowserEngine.get_page(proxy or m.default_proxy()) as page:
        captured: list = []
        m._attach_api_monitor(page, captured)

        reused = False
        if saved:
            m._restore_session(page, saved)
            if m._session_still_valid(page, captured, saved["token"]):
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
                    f"ou rode: venv/bin/python main.py {cfg.name}-login --save"
                )
            # M3: serializa relogin entre processos (cron + MCP simultâneos
            # não abrem dois browsers/logins na mesma conta).
            lock = Path(session_path).with_suffix(".lock")
            with open(lock, "w") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)  # ponytail: bloqueante; ok p/ 2-3 processos
                m._login_flow(page, username, password, captured)
                blocked = guard(page) if guard else []
                token = page.evaluate("() => localStorage.getItem('token')")
                m.save_session(
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


# ---- utilitários -----------------------------------------------------------


def default_proxy(cfg) -> str | None:
    """SIGMA_PROXY (ex.: socks5://100.x.y.z:1080 do microsocks no celular).

    ponytail: proxy cirúrgico — só os painéis passam pelo caminho
    alternativo; todo o resto da máquina segue a rota normal.
    (O BrowserEngine.get_page também aplica esse fallback — Hermes G1.)
    """
    return os.environ.get("SIGMA_PROXY") or None


def allow_destructive(cfg) -> bool:
    """CR-10: mutação destrutiva exige SIGMA_ALLOW_DESTRUCTIVE=1 no ambiente.

    'confirmar=True' preenchido pelo próprio LLM não é confirmação — o gate
    só abre com a variável setada por um humano. Gate ÚNICO compartilhado
    entre os sites (regra 4 do AGENTS.md).
    """
    return os.environ.get("SIGMA_ALLOW_DESTRUCTIVE") == "1"


@contextmanager
def logged_page(cfg, username: str, password: str, proxy: str = None, guard=None):
    """
    Contextmanager: abre o painel já logado e devolve
    SimpleNamespace(page, token, captured, blocked).

    `guard` é uma função f(page) -> lista de bloqueios; instalada APÓS o
    login (o POST de autenticação precisa passar). Use explore._guard
    para garantir modo somente-leitura.
    """
    m = cfg.module
    if not username or not password:
        raise ValueError("username e password são obrigatórios")

    with m.BrowserEngine.get_page(proxy) as page:
        captured: list = []
        m._attach_api_monitor(page, captured)
        m._login_flow(page, username, password, captured)
        blocked = guard(page) if guard else []
        yield SimpleNamespace(
            page=page,
            token=page.evaluate("() => localStorage.getItem('token')"),
            captured=captured,
            blocked=blocked,
        )


def login(cfg, username: str, password: str, proxy: str = None) -> dict:
    """
    Faz login no painel e retorna a sessão.

    Retorna: {"token": str, "cookies": [...], "captured": [...], "local_storage": {...}}
    Levanta RuntimeError com o corpo da resposta se o login falhar.
    """
    with logged_page(cfg, username, password, proxy) as s:
        return {
            "token": s.token,
            "cookies": s.page.context.cookies(),
            "captured": s.captured,
            "local_storage": s.page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            ),
        }
