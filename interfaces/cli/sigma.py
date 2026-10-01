import os
import secrets

import typer

from core.sigma.auth import SESSION_FILE, allow_destructive, login, save_session
from core.sigma.api import (
    customer_new_expiry,
    find_customer,
    open_client,
    project_response,
    set_expiry_on_payload,
)
from core.sigma.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
)


def register(app: typer.Typer):
    @app.command("sigma-login")
    def cli_sigma_login(save: bool = False):
        """Login no painel Sigma: imprime o token (usa SIGMA_USERNAME/SIGMA_PASSWORD)."""
        username = os.environ.get("SIGMA_USERNAME")
        password = os.environ.get("SIGMA_PASSWORD")
        if not username or not password:
            typer.secho("✖ Defina SIGMA_USERNAME e SIGMA_PASSWORD no ambiente.", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            sess = login(username, password)
        except Exception as e:
            typer.secho(f"✖ Login falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(
            f"✔ Token: {sess['token'][:16]}… (use --save para a sessão completa)",
            fg=typer.colors.GREEN,
        )  # CR-14: token completo não vai pro stdout/histórico
        if save:
            # B1: mesma via do CR-12 (0600 + troca atômica) — open() cru gravava 0644
            save_session(sess, SESSION_FILE)
            typer.secho(f"✔ Sessão completa salva em {SESSION_FILE}", fg=typer.colors.GREEN)

    @app.command("sigma-sync")
    def cli_sigma_sync(
        what: str = typer.Option("customers", help="customers|expiring|dashboard|resellers|statistics|all"),
        pages: int = typer.Option(5, help="Páginas de clientes (quando aplicável)."),
        per_page: int = typer.Option(100, help="Clientes por página (cap real da API: 100)."),
    ):
        """Sincroniza dados do painel Sigma para o banco local (read-only)."""
        if what not in (*SYNCERS, "all"):
            typer.secho(f"✖ 'what' inválido: {what}. Opções: {', '.join([*SYNCERS, 'all'])}", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with open_client() as client:
                if what == "all":
                    results = sync_all(client, pages, per_page)
                elif what == "customers":
                    results = [sync_customers(client, pages, per_page)]
                else:
                    results = [SYNCERS[what](client)]
        except Exception as e:
            typer.secho(f"✖ Sync falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        for r in results:
            extra = f" ({r['pages']} pág.)" if "pages" in r else ""
            typer.secho(f"✔ {r['what']}: {r['synced']} registro(s){extra}", fg=typer.colors.GREEN)

    @app.command("sigma-status")
    def cli_sigma_status():
        """Validade do token/painel Sigma + contagem do banco local."""
        try:
            with open_client() as client:
                me = client.me()
        except Exception as e:
            typer.secho(f"✖ Sigma inacessível: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        expiry = me.get("membership_expiry_date")
        typer.secho(f"✔ Usuário: {me.get('username')} | Conta/membership expira: {expiry or 'ilimitado'}", fg=typer.colors.GREEN)
        for kind, n in entities_summary().items():
            typer.echo(f"  {kind:18s} {n}")

    # ---- gestão de clientes (mutações; whitelist de 4 operações, sem bulk) ----

    @app.command("sigma-customer-create")
    def cli_sigma_customer_create(
        username: str = typer.Option(..., help="Username do cliente no painel."),
        package_id: str = typer.Option(..., help="ID do pacote (ex.: rdqLkQjWAE; ver GET /packages/list)."),
        server_id: str = typer.Option(..., help="ID do servidor (deve casar com o do pacote)."),
        name: str = typer.Option(None, help="Nome (padrão: username)."),
        email: str = typer.Option(None, help="Email (padrão: {username}@local.test)."),
        connections: int = typer.Option(1, help="Nº de conexões."),
        password: str = typer.Option(None, help="Senha (padrão: gerada; só letras/números/-/@/_)."),
        show_password: bool = typer.Option(False, "--show-password", help="Mostra a senha em claro."),
    ):
        """Cria um cliente no painel Sigma."""
        pwd = password or secrets.token_urlsafe(12)
        payload = {
            "username": username, "password": pwd, "password_confirmation": pwd,
            "name": name or username, "email": email or f"{username}@local.test",
            "connections": connections, "server_id": server_id, "package_id": package_id,
        }
        try:
            with open_client() as client:
                res = client.create_customer(payload)
        except Exception as e:
            typer.secho(f"✖ Create falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        cid = (res.get("data") or {}).get("id") if isinstance(res, dict) else None
        senha = pwd if show_password else pwd[:3] + "… (repetir com --show-password)"
        typer.secho(f"✔ Cliente criado: {username} (id: {cid or '?'}). Senha: {senha}",
                    fg=typer.colors.GREEN)  # CR-14: senha não vaza por padrão

    @app.command("sigma-customer-update")
    def cli_sigma_customer_update(
        customer_id: str = typer.Argument(..., help="ID do cliente (ex.: ze15VO34L5)."),
        note: str = typer.Option(None, help="Nova nota."),
        add_days: int = typer.Option(0, help="Estende a expiração em N dias."),
        set_expiry: str = typer.Option(None, help="Define expiração fixa YYYY-MM-DD."),
    ):
        """Edita nota e/ou expiração de um cliente (busca o row e reenvia o payload completo)."""
        if not (note or add_days or set_expiry):
            typer.secho("✖ Nada a mudar: use --note, --add-days ou --set-expiry.", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with open_client() as client:
                row = find_customer(client, customer_id)
                if not row:
                    typer.secho(f"✖ Cliente {customer_id} não encontrado na lista.", fg=typer.colors.RED)
                    raise typer.Exit(1)
                payload = dict(row)
                if note:
                    payload["note"] = note
                new_exp = None
                if add_days or set_expiry:
                    new_exp = customer_new_expiry(row, add_days, set_expiry)
                    if not new_exp:
                        typer.secho("✖ Row sem data de expiração — use --set-expiry.", fg=typer.colors.RED)
                        raise typer.Exit(1)
                    set_expiry_on_payload(row, payload, new_exp)
                res = client.update_customer(customer_id, payload)
        except typer.Exit:
            raise
        except Exception as e:
            typer.secho(f"✖ Update falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        extra = f" | expira: {new_exp}" if new_exp else ""
        typer.secho(f"✔ Cliente {customer_id} atualizado{extra}", fg=typer.colors.GREEN)

    @app.command("sigma-customer-delete")
    def cli_sigma_customer_delete(
        customer_id: str = typer.Argument(..., help="ID do cliente."),
        yes: bool = typer.Option(False, "--yes", help="Confirma a exclusão (soft delete)."),
    ):
        """Remove um cliente (SOFT delete — restaurável via POST /customers/restore)."""
        if not yes:
            typer.secho("✖ Destrutivo: confirme com --yes.", fg=typer.colors.RED)
            raise typer.Exit(1)
        if not allow_destructive():
            typer.secho("✖ CR-10: destrutivo exige SIGMA_ALLOW_DESTRUCTIVE=1 no ambiente.",
                        fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with open_client() as client:
                res = client.delete_customer(customer_id)
        except Exception as e:
            typer.secho(f"✖ Delete falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ Cliente {customer_id} removido (soft). Resposta: {project_response(res)}",
                    fg=typer.colors.GREEN)

    @app.command("sigma-customer-resync")
    def cli_sigma_customer_resync(customer_id: str = typer.Argument(..., help="ID do cliente.")):
        """Força resync do cliente no servidor IPTV."""
        try:
            with open_client() as client:
                res = client.resync_customer(customer_id)
        except Exception as e:
            typer.secho(f"✖ Resync falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ Resync enviado para {customer_id}: {res}", fg=typer.colors.GREEN)
