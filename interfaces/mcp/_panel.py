"""Engine compartilhado das tools MCP de painel (sigma-family).

Um único register_panel(mcp, m) registra as 12 tools de qualquer painel que
exponha o contrato de spec (o próprio módulo do site): SITE, DISPLAY, URL,
KIND (str|None), SyncWhat (Literal p/ schema) e os nomes de core.*
reexportados. Os workers `_op_<site>` dos módulos dos sites são
functools.partial(worker_genérico, módulo) — callables com a mesma assinatura
de antes (testes continuam importando/chamando igual), e TODA leitura de
nome de core.* é getattr(m, nome) NO CALL TIME (monkeypatch continua
funcionando). Site novo: ~45 linhas de spec; zero tool escrita à mão.
"""
import json
import os
import secrets

import anyio


# ---- workers genéricos (CR-01: browser/Playwright fora do event loop) ------
# assinatura: fn(m, ...args) — o módulo do site entra como 1º arg (partial).


def login_worker(m) -> str:
    username = os.environ.get("SIGMA_USERNAME")
    password = os.environ.get("SIGMA_PASSWORD")
    if not username or not password:
        return "Erro: defina SIGMA_USERNAME e SIGMA_PASSWORD no ambiente (ou --user via CLI)."
    try:
        sess = getattr(m, "login")(username, password)
    except Exception as e:
        return f"Login {m.SITE} falhou: {e}"
    return f"Token {m.SITE}: {sess['token'][:16]}… (completo não vai pro transcript)"


def sincronizar_worker(m, o_que: str, paginas: int, per_page: int) -> str:
    syncers = getattr(m, "SYNCERS")
    if o_que not in (*syncers, "all"):
        return f"'o_que' inválido: {o_que}. Opções: {', '.join([*syncers, 'all'])}"
    try:
        with getattr(m, "open_client")() as client:
            if o_que == "all":
                results = getattr(m, "sync_all")(client, paginas, per_page)
            elif o_que == "customers":
                results = [getattr(m, "sync_customers")(client, paginas, per_page)]
            else:
                results = [syncers[o_que](client)]
    except Exception as e:
        return f"Sync {m.SITE} falhou: {e}"
    return json.dumps(results, ensure_ascii=False)


def status_worker(m) -> str:
    try:
        with getattr(m, "open_client")() as client:
            me = client.me()
    except Exception as e:
        return f"{m.DISPLAY} inacessível: {e}"
    accounts = getattr(m, "load_accounts")()
    active = getattr(m, "resolve_active_account")(accounts) if accounts else None
    return json.dumps(
        {
            "usuario": me.get("username"),
            "conta_ativa": active["username"] if active else None,
            "conta_expira_em": me.get("membership_expiry_date") or "ilimitado",
            "banco_local": getattr(m, "entities_summary")(),
        },
        ensure_ascii=False,
    )


def listar_contas_worker(m) -> str:
    accounts = getattr(m, "load_accounts")()
    if not accounts:
        return json.dumps(
            {"contas": [], "nota": f"Nenhuma conta em {m.SITE}_accounts.json/env. "
             f"Cadastre com: main.py {m.SITE}-account add NOME"},
            ensure_ascii=False,
        )
    active = getattr(m, "resolve_active_account")(accounts)
    return json.dumps(
        {
            "contas": [
                {
                    "username": a["username"],
                    "ativa": bool(active and a["username"] == active["username"]),
                    "sessao_salva": getattr(m, "load_session")(
                        getattr(m, "session_path_for")(a["username"], accounts)
                    ) is not None,
                }
                for a in accounts
            ]
        },
        ensure_ascii=False,
    )


def trocar_conta_worker(m, username: str) -> str:
    accounts = getattr(m, "load_accounts")()
    if username not in {a["username"] for a in accounts}:
        return (f"Conta '{username}' não cadastrada. "
                f"Cadastre com: main.py {m.SITE}-account add {username}")
    getattr(m, "set_last_good")(username)
    try:
        with getattr(m, "open_client")() as client:
            me = client.me()
    except Exception as e:
        return (f"Ponteiro movido para {username}, mas a validação falhou "
                f"(sessão morta ou login demorou): {e}")
    return json.dumps(
        {"conta_ativa": username, "verificado_como": me.get("username")},
        ensure_ascii=False,
    )


def listar_pacotes_worker(m) -> str:
    ks = f"{m.KIND}." if m.KIND else ""
    try:
        with getattr(m, "open_client")() as client:
            getattr(m, "sync_servers_packages")(client)
    except Exception as e:
        return f"Sync de pacotes falhou: {e}"
    return json.dumps(
        {"servers": getattr(m, "list_entities")(f"{ks}server", limit=100),
         "packages": getattr(m, "list_entities")(f"{ks}package", limit=500)},
        ensure_ascii=False,
    )


def buscar_cliente_worker(m, termo: str, no_painel: bool) -> str:
    ks = f"{m.KIND}." if m.KIND else ""
    termo = (termo or "").strip()
    if not termo:
        return "Informe o termo de busca (username, nome, email ou id)."
    try:
        if no_painel:
            with getattr(m, "open_client")() as client:
                rows = getattr(m, "search_customers")(client, termo)
        else:
            rows = getattr(m, "search_entities")(f"{ks}customer", termo, limit=20)
    except Exception as e:
        return f"Busca falhou: {e}"
    return json.dumps(
        {"onde": "painel" if no_painel else "banco local",
         "total": len(rows),
         "clientes": [getattr(m, "project_customer")(r) for r in rows]},
        ensure_ascii=False,
    )


def listar_clientes_worker(m, pagina: int, por_pagina: int) -> str:
    ks = f"{m.KIND}." if m.KIND else ""
    try:
        rows = getattr(m, "list_entities")(
            f"{ks}customer", limit=max(1, min(por_pagina, 100)),
            offset=(max(1, pagina) - 1) * max(1, por_pagina))
    except Exception as e:
        return f"Listagem falhou: {e}"
    return json.dumps(
        {"pagina": pagina, "total": len(rows),
         "clientes": [getattr(m, "project_customer")(r) for r in rows]},
        ensure_ascii=False,
    )


def criar_cliente_worker(m, username: str, package_id: str, server_id: str,
                         connections: int = 1, password: str = None,
                         name: str = None, email: str = None,
                         mostrar_senha: bool = False) -> str:
    pwd = password or secrets.token_urlsafe(12)
    payload = {
        "username": username,
        "password": pwd,
        "password_confirmation": pwd,
        "name": name or username,
        "email": email or f"{username}@local.test",
        "connections": connections,
        "server_id": server_id,
        "package_id": package_id,
    }
    try:
        with getattr(m, "open_client")() as client:
            res = client.create_customer(payload)
    except Exception as e:
        return f"Criação falhou: {e}"
    cid = (res.get("data") or {}).get("id") if isinstance(res, dict) else None
    senha = pwd if mostrar_senha else pwd[:3] + "… (pedir mostrar_senha=True)"
    return json.dumps({"id": cid, "username": username, "senha": senha}, ensure_ascii=False)


def editar_cliente_worker(m, customer_id: str, note: str = None,
                          add_days: int = 0, set_expiry: str = None) -> str:
    if not note and not add_days and not set_expiry:
        return "Nada a mudar: informe note, add_days ou set_expiry."
    try:
        with getattr(m, "open_client")() as client:
            row = getattr(m, "find_customer")(client, customer_id)
            if not row:
                return f"Cliente {customer_id} não encontrado no painel."
            payload = dict(row)
            if note:
                payload["note"] = note
            ymd = getattr(m, "customer_new_expiry")(row, add_days=add_days, set_date=set_expiry)
            if ymd is None:
                return "Row sem campo de expiração — informe set_expiry (YYYY-MM-DD)."
            getattr(m, "set_expiry_on_payload")(row, payload, ymd)
            client.update_customer(customer_id, payload)
        return json.dumps({"id": str(customer_id), "note": payload.get("note"),
                           "expira_em": ymd}, ensure_ascii=False)
    except Exception as e:
        return f"Edição falhou: {e}"


def excluir_cliente_worker(m, customer_id: str, confirmar: bool = False) -> str:
    if not confirmar:
        return "Exclusão exige confirmar=True (soft delete)."
    if not getattr(m, "allow_destructive")():
        return "Gate destrutivo fechado: defina SIGMA_ALLOW_DESTRUCTIVE=1."
    try:
        with getattr(m, "open_client")() as client:
            res = client.delete_customer(customer_id)
        return json.dumps({"excluido": str(customer_id),
                           "resposta": getattr(m, "project_response")(res)}, ensure_ascii=False)
    except Exception as e:
        return f"Exclusão falhou: {e}"


def resync_cliente_worker(m, customer_id: str) -> str:
    try:
        with getattr(m, "open_client")() as client:
            res = client.resync_customer(customer_id)
        row = res if isinstance(res, dict) else {}
        return json.dumps({"id": row.get("id", str(customer_id)),
                           "cliente": getattr(m, "project_customer")(row)}, ensure_ascii=False)
    except Exception as e:
        return f"Resync falhou: {e}"


# ---- registro das tools -----------------------------------------------------


def _T(doc: str, m) -> str:
    ks = f"{m.KIND}." if m.KIND else ""
    host = m.URL.split("://", 1)[1]
    kind_note = (
        f"prefixo {m.KIND}.* — não mistura com o painel de origem"
        if m.KIND else "sem prefixo (painel original)"
    )
    return (
        doc.replace("__SITE__", m.SITE)
        .replace("__DISPLAY__", m.DISPLAY)
        .replace("__HOST__", host)
        .replace("__KIND_NOTE__", kind_note)
        .replace("__KS__", ks)
    )


def _tool(mcp, fn, name: str, doc: str, annotations: dict | None = None) -> None:
    fn.__name__ = name
    fn.__qualname__ = name
    fn.__doc__ = doc
    if annotations:
        fn.__annotations__.update(annotations)
    mcp.tool()(fn)


def register_panel(mcp, m) -> None:
    site = m.SITE
    run = anyio.to_thread.run_sync

    async def login() -> str:
        return await run(login_worker, m)

    _tool(mcp, login, f"login_{site}", _T("""
        Use quando: precisar de um login FRESCO no painel __SITE__
        (__HOST__ — as outras tools reutilizam a sessão salva).

        Retorna: token mascarado (16 primeiros caracteres).

        Cuidados: usa SIGMA_USERNAME/SIGMA_PASSWORD; abre browser real e
        leva ~1min; não copie __SITE___session.json entre máquinas.
        """, m))

    async def sincronizar(o_que, paginas: int = 5, per_page: int = 100) -> str:
        return await run(sincronizar_worker, m, o_que, paginas, per_page)

    _tool(mcp, sincronizar, f"sincronizar_{site}", _T("""
        Use quando: quiser espelhar dados do painel __SITE__ no banco local
        antes de consultar (grava com __KIND_NOTE__).
        Equivalente CLI: __SITE__-sync --what.

        Retorna: JSON com resumo por dataset ({what, synced, pages, status}).

        Cuidados: somente leitura no painel; per_page cap 100; paginas só
        afeta customers.
        """, m), {"o_que": m.SyncWhat})

    async def status() -> str:
        return await run(status_worker, m)

    _tool(mcp, status, f"status_{site}", _T("""
        Use quando: checar se o acesso ao __SITE__ está saudável antes de operar.

        Retorna: JSON {usuario, conta_ativa, conta_expira_em, banco_local}.

        Cuidados: abre browser real (~10s com sessão válida); conta_expira_em
        é da CONTA (membership), não do painel inteiro.
        """, m))

    async def listar_contas() -> str:
        return await run(listar_contas_worker, m)

    _tool(mcp, listar_contas, f"listar_contas_{site}", _T("""
        Use quando: precisar saber quais contas do __SITE__ estão
        cadastradas, qual está ativa e qual tem sessão salva.

        Retorna: JSON {contas: [{username, ativa, sessao_salva}]} — NUNCA
        senhas.

        Cuidados: leitura local (instantâneo). Ativa segue SIGMA_ACCOUNT >
        ponteiro .__SITE___last_good > primeira do arquivo. Paridade CLI:
        __SITE__-account list.
        """, m))

    async def trocar_conta(username: str) -> str:
        return await run(trocar_conta_worker, m, username)

    _tool(mcp, trocar_conta, f"trocar_conta_{site}", _T("""
        Use quando: o DONO pedir explicitamente operar o __SITE__ com outra
        conta cadastrada.

        Retorna: JSON {conta_ativa, verificado_como} após validar
        /api/auth/me no painel.

        Cuidados: muda o ponteiro GLOBAL do __SITE__; se a conta não tiver
        sessão salva, dispara login no browser (~1min). Nunca repasse
        senhas. Paridade CLI: __SITE__-account use.
        """, m))

    async def listar_pacotes() -> str:
        return await run(listar_pacotes_worker, m)

    _tool(mcp, listar_pacotes, f"listar_pacotes_{site}", _T("""
        Use quando: for criar/editar cliente no __SITE__ e precisar dos IDs
        de pacote e servidor (o par precisa ser coerente).

        Retorna: JSON {servers: [...], packages: [...]} — catálogo, sem PII.

        Cuidados: sincroniza o catálogo antes de listar (2 GETs); kinds
        __KS__server/__KS__package no banco. Paridade CLI:
        __SITE__-servers-packages.
        """, m))

    async def buscar_cliente(termo: str, no_painel: bool = False) -> str:
        return await run(buscar_cliente_worker, m, termo, no_painel)

    _tool(mcp, buscar_cliente, f"buscar_cliente_{site}", _T("""
        Use quando: tiver parte do username/nome/email/id de um cliente do
        __SITE__ e precisar do registro completo.

        Retorna: JSON {onde, total, clientes:[...]} — só campos públicos.

        Cuidados: padrão busca no BANCO LOCAL (dados do último
        sincronizar___SITE__); no_painel=True consulta ao vivo (lento).
        """, m))

    async def listar_clientes(pagina: int = 1, por_pagina: int = 20) -> str:
        return await run(listar_clientes_worker, m, pagina, por_pagina)

    _tool(mcp, listar_clientes, f"listar_clientes_{site}", _T("""
        Use quando: quiser folhear a base local de clientes do __SITE__.

        Retorna: JSON {pagina, total, clientes:[...]} — só campos públicos.

        Cuidados: lê o BANCO LOCAL; por_pagina cap 100; rode
        sincronizar___SITE__('customers') antes para dados atuais.
        """, m))

    async def criar_cliente(username: str, package_id: str, server_id: str,
                            connections: int = 1, password: str = None,
                            name: str = None, email: str = None,
                            mostrar_senha: bool = False) -> str:
        return await run(
            criar_cliente_worker, m, username, package_id, server_id,
            connections, password, name, email, mostrar_senha,
        )

    _tool(mcp, criar_cliente, f"criar_cliente_{site}", _T("""
        Use quando: precisar cadastrar um cliente novo no painel __SITE__.

        Retorna: JSON {id, username, senha} — senha mascarada a menos que
        mostrar_senha=True.

        Cuidados: package_id e server_id devem ser um par coerente (use
        listar_pacotes___SITE__); senha só letras/números/-/@/_; se senha
        não for passada, gera uma automática. MUTAÇÃO (cria no
        painel real). Paridade CLI: __SITE__-customer-create.
        """, m))

    async def editar_cliente(customer_id: str, note: str = None,
                             add_days: int = 0, set_expiry: str = None) -> str:
        return await run(
            editar_cliente_worker, m, customer_id, note, add_days, set_expiry,
        )

    _tool(mcp, editar_cliente, f"editar_cliente_{site}", _T("""
        Use quando: precisar anotar ou renovar a expiração de um cliente
        do __SITE__.

        Retorna: JSON {id, note, expira_em} com a nova data (YYYY-MM-DD).

        Cuidados: add_days soma na expiração atual; set_expiry (YYYY-MM-DD)
        substitui; painel é UTC-3 (grava 02:59:59Z do dia seguinte). MUTAÇÃO (edita no
        painel real). Paridade CLI: __SITE__-customer-update.
        """, m))

    async def excluir_cliente(customer_id: str, confirmar: bool = False) -> str:
        return await run(excluir_cliente_worker, m, customer_id, confirmar)

    _tool(mcp, excluir_cliente, f"excluir_cliente_{site}", _T("""
        Use quando: o usuário pedir EXPLICITAMENTE para remover um cliente
        do painel __SITE__.

        Retorna: JSON {excluido, resposta:{id, deleted_at, status}} — soft
        delete (recuperável via restore no painel).

        Cuidados: DESTRUTIVO — exige confirmar=True E o gate
        SIGMA_ALLOW_DESTRUCTIVE=1 no ambiente. Confira o id com
        buscar_cliente___SITE__ antes. Paridade CLI: __SITE__-customer-delete ID --yes.
        """, m))

    async def resync_cliente(customer_id: str) -> str:
        return await run(resync_cliente_worker, m, customer_id)

    _tool(mcp, resync_cliente, f"resync_cliente_{site}", _T("""
        Use quando: precisar do estado ATUAL de um cliente direto do painel
        __SITE__ (expiração, status, nota) sem esperar sync.

        Retorna: JSON {id, cliente:{campos públicos}} — NUNCA senha nem
        m3u_url/renew_url (contêm credenciais).

        Cuidados: dispara re-sincronização no provedor do cliente (GET no
        upstream, read-only). Paridade CLI: __SITE__-customer-resync.
        """, m))
