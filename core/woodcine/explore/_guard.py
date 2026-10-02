"""
Rede de segurança dos scripts de exploração do painel Sigma.

Regra de ouro: explorar NUNCA pode alterar nada no painel. O guard
intercepta toda request no nível do Playwright e aborta qualquer método
capaz de mutar estado (POST/PUT/PATCH/DELETE). Um clique acidental num
botão perigoso simplesmente não sai do browser.

Instale SEMPRE via `logged_page(..., guard=install_guard)` — depois do
login, para não bloquear o POST de autenticação.
"""
import typer

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def install_guard(page) -> list:
    """Instala o kill switch de rede. Retorna a lista de requests bloqueadas."""
    blocked: list = []

    def _route(route):
        try:
            if route.request.method.upper() in SAFE_METHODS:
                route.continue_()
            else:
                blocked.append(
                    {"method": route.request.method, "url": route.request.url}
                )
                route.abort("blocked-by-explorer-guard")
        except Exception:
            pass  # rota já tratada/fechada — nunca derruba a sessão

    page.route("**/*", _route)
    return blocked


def report_blocked(blocked: list):
    """Imprime o que o guard bloqueou — deve ser vazio numa exploração sadia."""
    if not blocked:
        typer.secho("✔ Guard: nenhuma request mutante tentada.", fg=typer.colors.GREEN)
        return
    typer.secho(f"⚠ Guard bloqueou {len(blocked)} request(s) mutante(s):", fg=typer.colors.YELLOW)
    for b in blocked:
        typer.secho(f"  {b['method']} {b['url']}", fg=typer.colors.YELLOW)
