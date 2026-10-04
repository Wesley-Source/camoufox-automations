"""CLI do Rocket Gestor — Django server-rendered (sessão de cookies, não-Bearer)."""
import json
import os

import typer

from core.database import count_entities
from core.rocketgestor.api import RocketGestorError, open_client
from core.rocketgestor.auth import (
    load_accounts,
    load_session,
    resolve_active_account,
    save_session,
)


def _allow_destructive() -> bool:
    # mesmo gate dos painéis irmãos (SIGMA_ALLOW_DESTRUCTIVE, regra 4 AGENTS.md)
    return os.environ.get("SIGMA_ALLOW_DESTRUCTIVE") == "1"


def register(app: typer.Typer):

    @app.command("rocketgestor-login")
    def cli_rocketgestor_login(
        save: bool = False,
        user: str = typer.Option(None, "--user", help="Login desta conta cadastrada."),
    ):
        """Sessão válida no Rocket Gestor (reusa cookies; login no browser se morta)."""
        from core.rocketgestor.auth import ensure_logged_page

        try:
            with ensure_logged_page() as s:
                username = s.account or "?"
                typer.secho(f"✔ Sessão Rocket Gestor OK ({username}).", fg=typer.colors.GREEN)
                if save:
                    save_session(s.page, username=username)
                    typer.secho("✔ Sessão salva (rocketgestor_session.json).", fg=typer.colors.GREEN)
        except Exception as e:
            typer.secho(f"✖ Login falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)

    @app.command("rocketgestor-status")
    def cli_rocketgestor_status():
        """Sessão + contagens do banco local (kinds rocketgestor.*)."""
        accounts = load_accounts()
        active = resolve_active_account(accounts) if accounts else None
        conta = f" | Conta ativa: {active['username']}" if active else ""
        sess_ok = load_session() is not None
        typer.secho(f"✔ Sessão salva: {'✔' if sess_ok else '✖ (rode rocketgestor-login --save)'}{conta}",
                    fg=typer.colors.GREEN if sess_ok else typer.colors.RED)
        typer.echo(f"  rocketgestor.client        {count_entities('rocketgestor.client')}")

    @app.command("rocketgestor-listar")
    def cli_rocketgestor_listar(
        status: str = typer.Option(None, "--status", help="Ativo|Vencido|Vence Hoje."),
        paginas: int = typer.Option(3, "--paginas", help="Páginas a varrer (≈15 clientes/pág)."),
    ):
        """Lista clientes do painel (tabela /clientes/)."""
        try:
            with open_client() as c:
                rows = c.list_clients(status=status, max_pages=paginas)
        except RocketGestorError as e:
            typer.secho(f"✖ {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        for r in rows:
            typer.echo(f"  {r['id']:>8s}  {r['nome'][:28]:28s} {r['login']:16s} "
                       f"{r['vencimento'][:10]:10s} {r['status']}")
        typer.echo(f"\n{len(rows)} cliente(s) em até {paginas} pág.")

    @app.command("rocketgestor-buscar")
    def cli_rocketgestor_buscar(termo: str = typer.Argument(..., help="Nome/login/telefone/id.")):
        """Busca cliente por nome, login, telefone ou id."""
        try:
            with open_client() as c:
                rows = c.find_client(termo)
        except RocketGestorError as e:
            typer.secho(f"✖ {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        if not rows:
            typer.echo("Nada encontrado.")
            return
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))

    @app.command("rocketgestor-sync")
    def cli_rocketgestor_sync(
        status: str = typer.Option(None, "--status"),
        paginas: int = typer.Option(35, "--paginas", help="≈15 clientes/pág."),
    ):
        """Espelha clientes em kinds rocketgestor.client no banco local."""
        try:
            with open_client() as c:
                res = c.sync_clients(status=status, max_pages=paginas)
        except RocketGestorError as e:
            typer.secho(f"✖ {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ {res['synced']} clientes sincronizados "
                    f"({count_entities('rocketgestor.client')} no banco).", fg=typer.colors.GREEN)

    @app.command("rocketgestor-criar")
    def cli_rocketgestor_criar(
        nome: str = typer.Option(...),
        usuario: str = typer.Option(...),
        vencimento: str = typer.Option(..., help="dd/mm/aaaa."),
        plano: str = typer.Option("Mensal", help="Texto do plano (mapeado p/ ID)."),
        valor: float = typer.Option(30.0),
        forma: str = typer.Option("Pix", help="Forma de pagamento (mapeada p/ ID)."),
        telas: int = typer.Option(1),
        senha: str = typer.Option("", help="Senha IPTV (opcional)."),
        telefone: str = typer.Option("11999999999", help="Só números c/ DDD."),
    ):
        """Cria cliente no Rocket (créditos inexistentes — zz_test_* livres)."""
        payload = {
            "nome": nome, "usuario": usuario, "senha": senha,
            "telefone_0": "BR", "telefone_1": telefone,
            "vencimento": vencimento, "hora_vencimento": "23:59",
            "plano": plano, "valor": valor, "forma_de_pagamento": forma,
            "telas": telas,
        }
        try:
            with open_client() as c:
                res = c.create_client(payload)
        except RocketGestorError as e:
            typer.secho(f"✖ {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        if not res.get("ok"):
            typer.secho(f"✖ Painel rejeitou: {res.get('alert')}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ Cliente {usuario} criado.", fg=typer.colors.GREEN)

    @app.command("rocketgestor-editar")
    def cli_rocketgestor_editar(
        cliente_id: str = typer.Argument(..., help="ID numérico (ver rocketgestor-listar)."),
        vencimento: str = typer.Option(None, help="ISO aaaa-mm-dd."),
        valor: float = typer.Option(None),
        plano: str = typer.Option(None, help="Texto do plano (mapeado p/ ID)."),
        forma: str = typer.Option(None, help="Forma de pagamento (OBRIGATÓRIA p/ o painel)."),
        telas: int = typer.Option(None),
    ):
        """Edita campos de um cliente (rota /cliente/editar?cliente_id=)."""
        overrides = {k: v for k, v in {
            "vencimento": vencimento, "valor": valor, "plano": plano,
            "forma_de_pagamento": forma, "telas": telas,
        }.items() if v is not None}
        if not overrides:
            typer.secho("✖ Nada a mudar: use --vencimento/--valor/--plano/--forma/--telas.",
                        fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with open_client() as c:
                res = c.update_client(cliente_id, overrides)
        except RocketGestorError as e:
            typer.secho(f"✖ {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        if not res.get("ok"):
            typer.secho(f"✖ Painel rejeitou: {res.get('alert')}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ Cliente {cliente_id} atualizado.", fg=typer.colors.GREEN)

    @app.command("rocketgestor-apagar")
    def cli_rocketgestor_apagar(
        cliente_id: str = typer.Argument(..., help="ID numérico."),
        yes: bool = typer.Option(False, "--yes"),
    ):
        """Apaga cliente (SOFT → lixeira, restaurável no painel)."""
        if not yes:
            typer.secho("✖ Destrutivo: confirme com --yes.", fg=typer.colors.RED)
            raise typer.Exit(1)
        if not _allow_destructive():
            typer.secho("✖ CR-10: destrutivo exige SIGMA_ALLOW_DESTRUCTIVE=1.", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with open_client() as c:
                res = c.delete_client(cliente_id)
        except RocketGestorError as e:
            typer.secho(f"✖ {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        if not res.get("ok"):
            typer.secho(f"✖ Falhou: {res.get('alert') or res.get('note')}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ Cliente {cliente_id} na lixeira (soft).", fg=typer.colors.GREEN)
