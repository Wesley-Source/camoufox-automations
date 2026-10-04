"""Engine compartilhado dos CLIs de painel (sigma-family).

Um único register_panel(app, m) registra os 10 comandos de qualquer painel
que exponha o contrato de spec (o próprio módulo do site):
  SITE, DISPLAY, URL, KIND (str|None), ACCOUNTS_FILE, SESSION_FILE e os
  nomes de core.* reexportados (load_accounts, login, open_client, ...).
Tudo é lido via getattr(m, nome) NO MOMENTO DA CHAMADA (padrão `m` do
panel_auth) — monkeypatch nos módulos dos sites continua funcionando.
Site novo: ~30 linhas de spec; zero comando escrito à mão.
"""
import json
import secrets
from pathlib import Path

import typer


def register_panel(app: typer.Typer, m) -> None:
    site = m.SITE
    display = m.DISPLAY
    url = m.URL
    kind = m.KIND
    ks = f"{kind}." if kind else ""
    kinds_short = f"{kind}.*" if kind else "sem prefixo"
    kind_note = (
        f"prefixados {kind}.* — não mistura com o lideriptv"
        if kind else "sem prefixo (painel original)"
    )
    indep = " — independente do lideriptv" if kind else ""
    accounts_name = Path(m.ACCOUNTS_FILE).name
    sync_help = "|".join([*m.SYNCERS, "all"])

    def _a(name):
        # late-binding: patch em interfaces.cli.<site>.<nome> continua valendo
        return getattr(m, name)

    def _T(doc: str) -> str:
        return (
            doc.replace("__SITE__", site)
            .replace("__DISPLAY__", display)
            .replace("__URL__", url)
            .replace("__KIND_NOTE__", kind_note)
            .replace("__KINDS__", kinds_short)
            .replace("__INDEP__", indep)
            .replace("__ACCOUNTS__", accounts_name)
        )

    def _cmd(fn, name: str, doc: str) -> None:
        fn.__name__ = name
        fn.__qualname__ = name
        fn.__doc__ = _T(doc)
        app.command(name)(fn)

    # ---- __SITE__-account -------------------------------------------------

    def cli_account(
        action: str = typer.Argument(..., help="list|use|add|remove"),
        name: str = typer.Argument(None, help="Username (use/add/remove)."),
    ):
        accounts = _a("load_accounts")()
        if action == "list":
            if not accounts:
                typer.echo(f"Nenhuma conta cadastrada ({accounts_name} + env).")
                raise typer.Exit(0)
            active = _a("resolve_active_account")(accounts)
            for a in accounts:
                u = a["username"]
                saved = _a("load_session")(_a("session_path_for")(u, accounts)) is not None
                has_sess = "✔" if saved else "–"
                mark = " ← ativa" if active and u == active["username"] else ""
                typer.echo(f"  {u:20s} sessão: {has_sess}{mark}")
            return

        if action == "use":
            if not name:
                typer.secho(f"✖ Uso: {site}-account use NOME", fg=typer.colors.RED)
                raise typer.Exit(1)
            if name not in {a["username"] for a in accounts}:
                typer.secho(f"✖ Conta {name} não cadastrada.", fg=typer.colors.RED)
                raise typer.Exit(1)
            _a("set_last_good")(name)
            typer.secho(f"✔ Conta ativa: {name} (próximo comando já usa).", fg=typer.colors.GREEN)
            return

        if action == "add":
            if not name:
                typer.secho(f"✖ Uso: {site}-account add NOME", fg=typer.colors.RED)
                raise typer.Exit(1)
            accs = _read_file_accounts(m)
            if any(a.get("username") == name for a in accs):
                typer.secho(f"✖ {name} já está no arquivo.", fg=typer.colors.RED)
                raise typer.Exit(1)
            pwd = typer.prompt(f"Senha de {name}", hide_input=True)
            accs.append({"username": name, "password": pwd})
            _write_file_accounts(m, accs)
            typer.secho(f"✔ Conta {name} cadastrada em {_a('ACCOUNTS_FILE')} (0600).", fg=typer.colors.GREEN)
            return

        if action == "remove":
            if not name:
                typer.secho(f"✖ Uso: {site}-account remove NOME", fg=typer.colors.RED)
                raise typer.Exit(1)
            accs = _read_file_accounts(m)
            kept = [a for a in accs if a.get("username") != name]
            if len(kept) == len(accs):
                typer.secho(f"✖ {name} não está no arquivo.", fg=typer.colors.RED)
                raise typer.Exit(1)
            _write_file_accounts(m, kept)
            typer.secho(f"✔ Conta {name} removida.", fg=typer.colors.GREEN)
            return

        typer.secho(f"✖ Ação inválida: {action}. Use list|use|add|remove.", fg=typer.colors.RED)
        raise typer.Exit(1)

    _cmd(cli_account, f"{site}-account", """
        Gerencia as contas do __SITE__ (fonte: __ACCOUNTS__, 0600).

        Use quando: cadastrar credenciais ou trocar a conta ativa do painel
        __SITE__ (__URL__)__INDEP__.
        Retorna: lista (nome | sessão | ativa — NUNCA senhas), confirmação.
        Cuidados: 'use' só move o ponteiro .__SITE___last_good.
        """)

    # ---- __SITE__-login ---------------------------------------------------

    def cli_login(
        save: bool = False,
        user: str = typer.Option(None, "--user", help="Login fresco desta conta cadastrada."),
    ):
        accounts = _a("load_accounts")()
        if user:
            acc = next((a for a in accounts if a["username"] == user), None)
            if not acc:
                typer.secho(f"✖ Conta {user} não está em {_a('ACCOUNTS_FILE')}.", fg=typer.colors.RED)
                raise typer.Exit(1)
            username, password = acc["username"], acc["password"]
        else:
            import os
            username = os.environ.get("SIGMA_USERNAME")
            password = os.environ.get("SIGMA_PASSWORD")
        if not username or not password:
            typer.secho("✖ Defina SIGMA_USERNAME e SIGMA_PASSWORD (ou use --user NOME).", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            sess = _a("login")(username, password)
        except Exception as e:
            typer.secho(f"✖ Login falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(
            f"✔ Token: {sess['token'][:16]}… (use --save para a sessão completa)",
            fg=typer.colors.GREEN,
        )
        if save:
            path = _a("session_path_for")(username, accounts) if accounts else _a("SESSION_FILE")
            _a("save_session")(sess, path, username=username if accounts else None)
            if accounts:
                _a("set_last_good")(username)
            typer.secho(f"✔ Sessão completa salva em {path}", fg=typer.colors.GREEN)

    _cmd(cli_login, f"{site}-login", """
        Login FRESCO no painel __SITE__ (as outras forças reutilizam a sessão).

        Use quando: sessão morta do __SITE__ e sem env pra relogin.
        Retorna: token mascarado (16 chars).
        Cuidados: --save grava sessão 0600 no arquivo DA CONTA; cf_clearance
        é IP-bound — não copie sessões entre máquinas.
        """)

    # ---- __SITE__-sync ----------------------------------------------------

    def cli_sync(
        what: str = typer.Option("customers", help=f"{sync_help}"),
        pages: int = typer.Option(5, help="Páginas de clientes (quando aplicável)."),
        per_page: int = typer.Option(100, help="Clientes por página (cap real da API: 100)."),
    ):
        syncers = _a("SYNCERS")
        if what not in (*syncers, "all"):
            typer.secho(f"✖ 'what' inválido: {what}. Opções: {', '.join([*syncers, 'all'])}", fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with _a("open_client")() as client:
                if what == "all":
                    results = _a("sync_all")(client, pages, per_page)
                elif what == "customers":
                    results = [_a("sync_customers")(client, pages, per_page)]
                else:
                    results = [syncers[what](client)]
        except Exception as e:
            typer.secho(f"✖ Sync falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        for r in results:
            extra = f" ({r['pages']} pág.)" if "pages" in r else ""
            typer.secho(f"✔ {r['what']}: {r['synced']} registro(s){extra}", fg=typer.colors.GREEN)

    _cmd(cli_sync, f"{site}-sync", """
        Espelha dados do painel __SITE__ no banco local (read-only; kinds
        __KIND_NOTE__).

        Use quando: antes de consultar/buscar clientes locais do __SITE__.
        Retorna: resumo por dataset ({what, synced, pages, status}).
        Cuidados: --what valida contra a whitelist; --pages só afeta
        customers. Paridade MCP: sincronizar___SITE__.
        """)

    # ---- __SITE__-status --------------------------------------------------

    def cli_status():
        try:
            with _a("open_client")() as client:
                me = client.me()
        except Exception as e:
            typer.secho(f"✖ {display} inacessível: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        expiry = me.get("membership_expiry_date")
        accounts = _a("load_accounts")()
        active = _a("resolve_active_account")(accounts) if accounts else None
        conta = f" | Conta ativa: {active['username']}" if active else ""
        typer.secho(f"✔ Usuário: {me.get('username')}{conta} | Conta/membership expira: {expiry or 'ilimitado'}", fg=typer.colors.GREEN)
        for kind_name, n in _a("entities_summary")().items():
            typer.echo(f"  {kind_name:24s} {n}")

    _cmd(cli_status, f"{site}-status", """
        Saúde do acesso __SITE__ + banco local (kinds __KINDS__).

        Use quando: checagem rápida antes de operar o __SITE__.
        Retorna: usuário, expiração da CONTA/membership e contagens.
        Cuidados: abre browser (~10s com sessão válida).
        """)

    # ---- __SITE__-customer-create -----------------------------------------

    def cli_customer_create(
        username: str = typer.Option(..., help="Username do cliente no painel."),
        package_id: str = typer.Option(..., help="ID do pacote (ver __SITE__-servers-packages)."),
        server_id: str = typer.Option(..., help="ID do servidor (deve casar com o do pacote)."),
        name: str = typer.Option(None, help="Nome (padrão: username)."),
        email: str = typer.Option(None, help="Email (padrão: {username}@local.test)."),
        connections: int = typer.Option(1, help="Nº de conexões."),
        password: str = typer.Option(None, help="Senha (padrão: gerada; só letras/números/-/@/_)."),
        show_password: bool = typer.Option(False, "--show-password", help="Mostra a senha em claro."),
    ):
        pwd = password or secrets.token_urlsafe(12)
        payload = {
            "username": username, "password": pwd, "password_confirmation": pwd,
            "name": name or username, "email": email or f"{username}@local.test",
            "connections": connections, "server_id": server_id, "package_id": package_id,
        }
        try:
            with _a("open_client")() as client:
                res = client.create_customer(payload)
        except Exception as e:
            typer.secho(f"✖ Create falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        cid = (res.get("data") or {}).get("id") if isinstance(res, dict) else None
        senha = pwd if show_password else pwd[:3] + "… (repetir com --show-password)"
        typer.secho(f"✔ Cliente criado: {username} (id: {cid or '?'}). Senha: {senha}",
                    fg=typer.colors.GREEN)  # CR-14: senha não vaza por padrão

    _cmd(cli_customer_create, f"{site}-customer-create", """
        Cria um cliente no painel __DISPLAY__.

        Use quando: onboarding de cliente novo. Ache o par package/server
        com __SITE__-servers-packages (pacote de outro servidor dá 400).
        Retorna: id do cliente + senha (mascarada; --show-password revela).
        Cuidados: MUTAÇÃO real. Paridade MCP: criar_cliente___SITE__.
        """)

    # ---- __SITE__-customer-update -----------------------------------------

    def cli_customer_update(
        customer_id: str = typer.Argument(..., help="ID do cliente."),
        note: str = typer.Option(None, help="Nova nota."),
        add_days: int = typer.Option(0, help="Estende a expiração em N dias."),
        set_expiry: str = typer.Option(None, help="Define expiração fixa YYYY-MM-DD."),
    ):
        if not (note or add_days or set_expiry):
            typer.secho("✖ Nada a mudar: use --note, --add-days ou --set-expiry.", fg=typer.colors.RED)
            raise typer.Exit(1)
        new_exp = None
        try:
            with _a("open_client")() as client:
                row = _a("find_customer")(client, customer_id)
                if not row:
                    typer.secho(f"✖ Cliente {customer_id} não encontrado na lista.", fg=typer.colors.RED)
                    raise typer.Exit(1)
                payload = dict(row)
                if note:
                    payload["note"] = note
                if add_days or set_expiry:
                    new_exp = _a("customer_new_expiry")(row, add_days, set_expiry)
                    if not new_exp:
                        typer.secho("✖ Row sem data de expiração — use --set-expiry.", fg=typer.colors.RED)
                        raise typer.Exit(1)
                    _a("set_expiry_on_payload")(row, payload, new_exp)
                res = client.update_customer(customer_id, payload)
        except typer.Exit:
            raise
        except Exception as e:
            typer.secho(f"✖ Update falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        extra = f" | expira: {new_exp}" if new_exp else ""
        typer.secho(f"✔ Cliente {customer_id} atualizado{extra}", fg=typer.colors.GREEN)

    _cmd(cli_customer_update, f"{site}-customer-update", """
        Edita nota e/ou expiração de um cliente no __DISPLAY__.

        Use quando: renovação (--add-days) ou ajuste de vencimento/nota.
        Retorna: confirmação com nova expiração (YYYY-MM-DD).
        Cuidados: MUTAÇÃO — reenvia o payload completo do row; ao menos
        uma opção obrigatória. Paridade MCP: editar_cliente___SITE__.
        """)

    # ---- __SITE__-customer-delete -----------------------------------------

    def cli_customer_delete(
        customer_id: str = typer.Argument(..., help="ID do cliente."),
        yes: bool = typer.Option(False, "--yes", help="Confirma a exclusão (soft delete)."),
    ):
        if not yes:
            typer.secho("✖ Destrutivo: confirme com --yes.", fg=typer.colors.RED)
            raise typer.Exit(1)
        if not _a("allow_destructive")():
            typer.secho("✖ CR-10: destrutivo exige SIGMA_ALLOW_DESTRUCTIVE=1 no ambiente.",
                        fg=typer.colors.RED)
            raise typer.Exit(1)
        try:
            with _a("open_client")() as client:
                res = client.delete_customer(customer_id)
        except Exception as e:
            typer.secho(f"✖ Delete falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ Cliente {customer_id} removido (soft). Resposta: {_a('project_response')(res)}",
                    fg=typer.colors.GREEN)

    _cmd(cli_customer_delete, f"{site}-customer-delete", """
        Remove um cliente do __DISPLAY__ (SOFT delete — restaurável no painel).

        Use quando: o DONO pediu explicitamente a remoção.
        Retorna: resposta projetada (id/deleted_at/status — sem segredos).
        Cuidados: exige --yes E SIGMA_ALLOW_DESTRUCTIVE=1 (CR-10: flag
        preenchida pelo agente não é confirmação). Paridade MCP:
        excluir_cliente___SITE__(confirmar=True).
        """)

    # ---- __SITE__-customer-resync -----------------------------------------

    def cli_customer_resync(customer_id: str = typer.Argument(..., help="ID do cliente.")):
        try:
            with _a("open_client")() as client:
                res = client.resync_customer(customer_id)
        except Exception as e:
            typer.secho(f"✖ Resync falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(
            f"✔ Resync enviado para {customer_id}: {_a('project_customer')(res)}",
            fg=typer.colors.GREEN,
        )

    _cmd(cli_customer_resync, f"{site}-customer-resync", """
        Força o resync do cliente no servidor IPTV (__DISPLAY__).

        Use quando: cliente atualizou a lista no app e não vê canais novos.
        Retorna: só campos públicos do cliente (nunca senha/m3u_url).
        Cuidados: mutação inofensiva (não altera dados). Paridade MCP:
        resync_cliente___SITE__.
        """)

    # ---- __SITE__-customer-playlist ---------------------------------------

    def cli_customer_playlist(
        customer_id: str = typer.Argument(..., help="ID do cliente."),
        mascarar: bool = typer.Option(False, "--mascarar", help="Esconde senha/m3u_url (padrão: em claro — decisão do dono 03/10/2026)."),
    ):
        try:
            with _a("open_client")() as client:
                row = _a("find_customer")(client, customer_id)
                if not row:
                    typer.secho(f"✖ Cliente {customer_id} não encontrado no painel (rode {site}-sync se o banco local está stale).", fg=typer.colors.RED)
                    raise typer.Exit(1)
                fields = {
                    "id": str(row.get("id", customer_id)),
                    "username": row.get("username"),
                    "password": row.get("password"),
                    "m3u_url": row.get("m3u_url"),
                    "status": row.get("status"),
                    "expira_em": row.get("expiry_date") or row.get("expires_at"),
                }
                try:
                    pl = client.customer_playlist(customer_id)
                    if isinstance(pl, list):
                        extras = [x for x in pl if isinstance(x, dict) and "template" not in x]
                        if extras:
                            fields["playlist_templates"] = extras
                except Exception:
                    pass  # credenciais do row bastam; rota pode devolver só templates
        except typer.Exit:
            raise
        except Exception as e:
            typer.secho(f"✖ Playlist falhou: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        if mascarar:
            for k in ("password", "m3u_url"):
                if fields.get(k):
                    fields[k] = str(fields[k])[:4] + "…"
        typer.echo(json.dumps(fields, ensure_ascii=False, indent=2))

    _cmd(cli_customer_playlist, f"{site}-customer-playlist", """
        Mostra os dados da aba Playlist do cliente (credenciais IPTV + apps).

        Use quando: o cliente pediu os próprios dados para configurar o app.
        Retorna: username/senha IPTV EM CLARO (exceção documentada da regra
        5, decisão do dono 03/10/2026) + status/expiração + template se houver.
        Cuidados: --mascarar esconde os segredos (p/ conversa pública).
        Paridade MCP: playlist_cliente(painel="__SITE__").
        """)

    # ---- __SITE__-servers-packages ----------------------------------------

    def cli_servers_packages(
        json_out: bool = typer.Option(False, "--json", help="Catálogo completo em JSON."),
    ):
        try:
            with _a("open_client")() as client:
                res = _a("sync_servers_packages")(client)
        except Exception as e:
            typer.secho(f"✖ Erro: {e}", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"✔ {res['servers']} servidor(es), {res['packages']} pacote(s) "
                    f"({res['synced']} gravados)", fg=typer.colors.GREEN)
        if json_out:
            typer.echo(json.dumps(
                {"servers": _a("list_entities")(f"{ks}server", limit=100),
                 "packages": _a("list_entities")(f"{ks}package", limit=500)},
                ensure_ascii=False,
            ))

    _cmd(cli_servers_packages, f"{site}-servers-packages", """
        Sincroniza e lista o catálogo de servers + packages do __SITE__.

        Use quando: antes de criar/editar cliente no __SITE__ (fase CRUD).
        Retorna: contagens; --json traz o catálogo completo (sem PII).
        Cuidados: 2 GETs no painel. Paridade MCP: listar_pacotes___SITE__.
        """)


def _read_file_accounts(m) -> list:
    try:
        data = json.loads(Path(m.ACCOUNTS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_file_accounts(m, accs: list) -> None:
    import os
    fd = os.open(m.ACCOUNTS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(accs, f, indent=2, ensure_ascii=False)
