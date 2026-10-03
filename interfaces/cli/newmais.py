import json
import secrets
import os
from pathlib import Path

import typer

from core.newmais.auth import (
    NEWMAIS_ACCOUNTS_FILE,
    NEWMAIS_SESSION_FILE,
    allow_destructive,
    load_accounts,
    load_session,
    login,
    resolve_active_account,
    save_session,
    session_path_for,
    set_last_good,
)
from core.newmais.api import (
    customer_new_expiry,
    find_customer,
    open_client,
    project_customer,
    project_response,
    set_expiry_on_payload,
)
from core.database import list_entities
from core.newmais.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
    sync_servers_packages,
)


def _read_file_accounts() -> list:
    try:
        data = json.loads(Path(NEWMAIS_ACCOUNTS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_file_accounts(accs: list) -> None:
    fd = os.open(NEWMAIS_ACCOUNTS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(accs, f, indent=2, ensure_ascii=False)


def _has_saved_session(username: str, accounts: list) -> bool:
    return load_session(session_path_for(username, accounts)) is not None


def register(app: typer.Typer):
    @app.command("newmais-account")
    def cli_newmais_account(
        action: str = typer.Argument(..., help="list|use|add|remove"),
        name: str = typer.Argument(None, help="Username (use/add/remove)."),
    ):
        """
        Gerencia as contas do newmais (fonte: newmais_accounts.json, 0600).

        Use quando: cadastrar credenciais ou trocar a conta ativa do painel
        newmais (https://newmais.sigma.vin) — independente do lideriptv.
        Retorna: lista (nome | sessão | ativa — NUNCA senhas), confirmação.
        Cuidados: 'use' só move o ponteiro .newmais_last_good.
        """
        if action == "list":
            accounts = load_accounts()
            if not accounts:
                typer.echo("Nenhuma conta cadastrada (newmais_accounts.json + env).")
                raise typer.Exit(0)
            active = resolve_active_account(accounts)
            for a in accounts:
                u = a["username"]
                has_sess = "✔" if _has_saved_session(u, accounts) else "–"
                mark = " ← ativa" if active and u == active["username"] else ""
                typer.echo(f"  {u:20s} sessão: {has_sess}{mark}")
            return

        if action == "use":
            if not name:
                typer.secho("✖ Uso: newmais-account use NOME", fg=typer.colors.RED)
                raise typer.Exit(1)
            if name not in {a["username"] for a in load_accounts()}:
                typer.secho(f"✖ Conta {name} não cadastrada.", fg=typer.colors.RED)
                raise typer.Exit(1)
            set_last_good(name)
            typer.secho(f"✔ Conta ativa: {name} (próximo comando já usa).", fg=typer.colors.GREEN)
            return

        if action == "add":
            if not name:
                typer.secho("✖ Uso: newmais-account add NOME", fg=typer.colors.RED)
                raise typer.Exit(1)
            accs = _read_file_accounts()
            if any(a.get("username") == name for a in accs):
                typer.secho(f"✖ {name} já está no arquivo.", fg=typer.colors.RED)
                raise typer.Exit(1)
            pwd = typer.prompt(f"Senha de {name}", hide_input=True)
            accs.append({"username": name, "password": pwd})
            _write_file_accounts(accs)
            typer.secho(f"✔ Conta {name} cadastrada em {NEWMAIS_ACCOUNTS_FILE} (0600).", fg=typer.colors.GREEN)
            return

        if action == "remove":
            if not name:
                typer.secho("✖ Uso: newmais-account remove NOME", fg=typer.colors.RED)
                raise typer.Exit(1)
            accs = _read_file_accounts()
            kept = [a for a in accs if a.get("username") != name]
            if len(kept) == len(accs):
                typer.secho(f"✖ {name} não está no arquivo.", fg=typer.colors.RED)
                raise typer.Exit(1)
            _write_file_accounts(kept)
            typer.secho(f"✔ Conta {name} removida.", fg=typer.colors.GREEN)
            return

        typer.secho(f"✖ Ação inválida: {action}. Use list|use|add|remove.", fg=typer.colors.RED)
        raise typer.Exit(1)

    @app.command("newmais-login")
    def cli_newmais_login(
        save: bool = False,
        user: str = typer.Option(None, "--user", help="Login fresco desta conta cadastrada."),
    ):
        """
        Login FRESCO no painel newmais (as outras forças reutilizam a sessão).

        Use quando: sessão morta do newmais e sem env pra relogin.
        Retorna: token mascarado (16 chars).
        Cuidados: --save grava sessão 0600 no arquivo DA CONTA; cf_clearance
        é IP-bound — não copie sessões entre máquinas.
        """
        accounts = load_accounts()
        if user:
            acc = next((a for a in accounts if a["username"] == user), None)
            if not acc:
                typer.secho(f"✖ Conta {user} não está em {NEWMAIS_ACCOUNTS_FILE}.", fg=typer.colors.RED)
                raise typer.Exit(1)
            username, password = acc["username"], acc["password"]
        else:
            username = os.environ.get("SIGMA_USERNAME")
            password = os.environ.get("SIGMA_PASSWORD")
        if not username or not password:
            typer.secho("✖ Defina SIGMA_USERNAME e SIGMA_PASSWORD (ou use --user NOME).", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            sess = login(username, password)
        except Exception as e:
            typer.secho(f"✖ Login falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(
            f"✔ Token: {sess['token'][:16]}… (use --save para a sessão completa)",
            fg=typer.colors.GREEN,
        )
        if save:
            path = session_path_for(username, accounts) if accounts else NEWMAIS_SESSION_FILE
            save_session(sess, path, username=username if accounts else None)
            if accounts:
                set_last_good(username)
            typer.secho(f"✔ Sessão completa salva em {path}", fg=typer.colors.GREEN)

    @app.command("newmais-sync")
    def cli_newmais_sync(
        what: str = typer.Option("customers", help="customers|expiring|dashboard|resellers|statistics|servers_packages|all"),
        pages: int = typer.Option(5, help="Páginas de clientes (quando aplicável)."),
        per_page: int = typer.Option(100, help="Clientes por página (cap real da API: 100)."),
    ):
        """
        Espelha dados do painel newmais no banco local (read-only; kinds
        prefixados newmais.* — não mistura com o lideriptv).

        Use quando: antes de consultar/buscar clientes locais do newmais.
        Retorna: resumo por dataset ({what, synced, pages, status}).
        Cuidados: --what valida contra a whitelist; --pages só afeta
        customers. Paridade MCP: sincronizar_newmais.
        """
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

    @app.command("newmais-status")
    def cli_newmais_status():
        """
        Saúde do acesso newmais + banco local (kinds newmais.*).

        Use quando: checagem rápida antes de operar o newmais.
        Retorna: usuário, expiração da CONTA/membership e contagens.
        Cuidados: abre browser (~10s com sessão válida).
        """
        try:
            with open_client() as client:
                me = client.me()
        except Exception as e:
            typer.secho(f"✖ Newmais inacessível: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        expiry = me.get("membership_expiry_date")
        accounts = load_accounts()
        active = resolve_active_account(accounts) if accounts else None
        conta = f" | Conta ativa: {active['username']}" if active else ""
        typer.secho(f"✔ Usuário: {me.get('username')}{conta} | Conta/membership expira: {expiry or 'ilimitado'}", fg=typer.colors.GREEN)
        for kind, n in entities_summary().items():
            typer.echo(f"  {kind:24s} {n}")

    @app.command("newmais-customer-create")
    def cli_newmais_customer_create(
        username: str = typer.Option(..., help="Username do cliente no painel."),
        package_id: str = typer.Option(..., help="ID do pacote (ver newmais-servers-packages)."),
        server_id: str = typer.Option(..., help="ID do servidor (deve casar com o do pacote)."),
        name: str = typer.Option(None, help="Nome (padrão: username)."),
        email: str = typer.Option(None, help="Email (padrão: {username}@local.test)."),
        connections: int = typer.Option(1, help="Nº de conexões."),
        password: str = typer.Option(None, help="Senha (padrão: gerada; só letras/números/-/@/_)."),
        show_password: bool = typer.Option(False, "--show-password", help="Mostra a senha em claro."),
    ):
        """
        Cria um cliente no painel Newmais.

        Use quando: onboarding de cliente novo. Ache o par package/server
        com newmais-servers-packages (pacote de outro servidor dá 400).
        Retorna: id do cliente + senha (mascarada; --show-password revela).
        Cuidados: MUTAÇÃO real. Paridade MCP: criar_cliente_newmais.
        """
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

    @app.command("newmais-customer-update")
    def cli_newmais_customer_update(
        customer_id: str = typer.Argument(..., help="ID do cliente."),
        note: str = typer.Option(None, help="Nova nota."),
        add_days: int = typer.Option(0, help="Estende a expiração em N dias."),
        set_expiry: str = typer.Option(None, help="Define expiração fixa YYYY-MM-DD."),
    ):
        """
        Edita nota e/ou expiração de um cliente no Newmais.

        Use quando: renovação (--add-days) ou ajuste de vencimento/nota.
        Retorna: confirmação com nova expiração (YYYY-MM-DD).
        Cuidados: MUTAÇÃO — reenvia o payload completo do row; ao menos
        uma opção obrigatória. Paridade MCP: editar_cliente_newmais.
        """
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

    @app.command("newmais-customer-delete")
    def cli_newmais_customer_delete(
        customer_id: str = typer.Argument(..., help="ID do cliente."),
        yes: bool = typer.Option(False, "--yes", help="Confirma a exclusão (soft delete)."),
    ):
        """
        Remove um cliente do Newmais (SOFT delete — restaurável no painel).

        Use quando: o DONO pediu explicitamente a remoção.
        Retorna: resposta projetada (id/deleted_at/status — sem segredos).
        Cuidados: exige --yes E SIGMA_ALLOW_DESTRUCTIVE=1 (CR-10: flag
        preenchida pelo agente não é confirmação). Paridade MCP:
        excluir_cliente_newmais(confirmar=True).
        """
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

    @app.command("newmais-customer-resync")
    def cli_newmais_customer_resync(customer_id: str = typer.Argument(..., help="ID do cliente.")):
        """
        Força o resync do cliente no servidor IPTV (Newmais).

        Use quando: cliente atualizou a lista no app e não vê canais novos.
        Retorna: só campos públicos do cliente (nunca senha/m3u_url).
        Cuidados: mutação inofensiva (não altera dados). Paridade MCP:
        resync_cliente_newmais.
        """
        try:
            with open_client() as client:
                res = client.resync_customer(customer_id)
        except Exception as e:
            typer.secho(f"✖ Resync falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(
            f"✔ Resync enviado para {customer_id}: {project_customer(res)}",
            fg=typer.colors.GREEN,
        )

    @app.command("newmais-servers-packages")
    def cli_newmais_servers_packages(
        json_out: bool = typer.Option(False, "--json", help="Catálogo completo em JSON."),
    ):
        """
        Sincroniza e lista o catálogo de servers + packages do newmais.

        Use quando: antes de criar/editar cliente no newmais (fase CRUD).
        Retorna: contagens; --json traz o catálogo completo (sem PII).
        Cuidados: 2 GETs no painel. Paridade MCP: listar_pacotes_newmais.
        """
        try:
            with open_client() as client:
                res = sync_servers_packages(client)
        except Exception as e:
            typer.secho(f"✖ Erro: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ {res['servers']} servidor(es), {res['packages']} pacote(s) "
                    f"({res['synced']} gravados)", fg=typer.colors.GREEN)
        if json_out:
            typer.echo(json.dumps(
                {"servers": list_entities("newmais.server", limit=100),
                 "packages": list_entities("newmais.package", limit=500)},
                ensure_ascii=False,
            ))
