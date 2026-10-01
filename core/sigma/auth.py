"""
Scraper do painel Sigma (https://lideriptv.sigma.st).

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

from core.browser import BrowserEngine

SIGMA_URL = "https://lideriptv.sigma.st"
SIGMA_API = SIGMA_URL + "/api"
_BODY_SNIPPET = 4000  # ponytail: guardamos só um trecho de cada response no log
SESSION_FILE = str(Path(__file__).resolve().parents[2] / "sigma_session.json")  # CR-25
_VALIDATE_SETTLE = 8  # ponytail: janela p/ o SPA devolver 401 ou redirecionar; subir se o painel ficar mais lento


def _attach_api_monitor(page, captured: list):
    """Captura toda request/response /api/* para análise e debugging."""

    def on_response(resp):
        try:
            if "/api" not in resp.url:
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
    page.goto(SIGMA_URL, wait_until="domcontentloaded", timeout=60_000)
    # O form do SPA demora a renderizar — espera explícita, sem sleep fixo.
    page.wait_for_selector("input[name=username]", timeout=120_000)
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("#kt_sign_in_submit")

    # Sucesso = token aparece no localStorage (o app salva após o POST).
    try:
        page.wait_for_function(
            "() => !!localStorage.getItem('token')", timeout=60_000
        )
    except Exception:
        login_resp = next(
            (c for c in reversed(captured) if "/api/auth/login" in c["url"]), None
        )
        detail = login_resp["response_body"] if login_resp else "sem resposta capturada"
        raise RuntimeError(f"Login Sigma falhou. Resposta: {detail}")


def load_session(path: str = SESSION_FILE) -> dict | None:
    """Sessão salva (token+cookies) ou None se ausente/corrompida/incompleta."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return s if s.get("token") and s.get("cookies") else None


def save_session(sess: dict, path: str = SESSION_FILE) -> None:
    """CR-12: 0600 + troca atômica — token+cookies nunca ficam legíveis para
    grupo/outros nem pela metade escritos. M3: tmp por-pid (duas corridas
    não se truncam) e arquivo nasce 0600 (sem janela write→chmod)."""
    p = Path(path)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(sess, f, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


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
    Validade decidida pelo SERVIDOR: GET /api/auth/me com o token (200 = válido).
    Complementos passivos: redireção pro sign-in, form de login renderizado
    ou qualquer 401 em /api/* na janela de observação.
    """
    try:
        page.goto(SIGMA_URL, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(_VALIDATE_SETTLE)  # SPA usa websocket (Pusher) — networkidle nunca assenta
        if "sign-in" in page.url:
            return False
        # Form de login renderizado = desautenticado, mesmo se a URL ainda não mudou.
        if page.locator("input[name=username]").count() > 0:
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


@contextmanager
def ensure_logged_page(username: str = None, password: str = None, proxy: str = None,
                       guard=None, session_path: str = SESSION_FILE):
    """
    Como logged_page, mas reutiliza a sessão salva se ainda válida.

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
                    "ou rode: venv/bin/python main.py sigma-login --save"
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
    Contextmanager: abre o painel Sigma já logado e devolve
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
    Faz login no painel Sigma e retorna a sessão.

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
