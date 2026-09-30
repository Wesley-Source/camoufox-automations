"""
Scraper do painel Sigma (https://lideriptv.sigma.st).

Fluxo de auth descoberto via recon do bundle JS (assets/ApiService-*.js):
- Login: POST /api/auth/login  {username, password}
- Token: salvo em localStorage["token"], enviado depois como "Authorization: Bearer <token>"
- Bloqueio Cloudflare: resposta do login vem como página HTML (cf-footer-ip / Ray ID)

O login é feito via navegador (Camoufox) para passar no Cloudflare e capturar
o cf_clearance; ao final devolvemos token + cookies + log de requests /api/*.
"""
from contextlib import contextmanager
from types import SimpleNamespace

from core.browser import BrowserEngine

SIGMA_URL = "https://lideriptv.sigma.st"
SIGMA_API = SIGMA_URL + "/api"
_BODY_SNIPPET = 4000  # ponytail: guardamos só um trecho de cada response no log


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
            captured.append({
                "method": resp.request.method,
                "url": resp.url,
                "status": resp.status,
                "post_data": resp.request.post_data,
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
