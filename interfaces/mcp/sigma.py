import json
import os
import secrets
from typing import Literal

import anyio

from core.sigma.api import (
    customer_new_expiry,
    find_customer,
    open_client,
    project_customer,
    project_response,
    search_customers,
    set_expiry_on_payload,
)
from core.database import list_entities, search_entities
from core.sigma.auth import (
    allow_destructive,
    load_accounts,
    load_session,
    login,
    resolve_active_account,
    session_path_for,
    set_last_good,
)
from core.sigma.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
    sync_servers_packages,
)


# ---- implementações síncronas (CR-01: browser/Playwright fora do event loop) --


def _login_sigma() -> str:
    username = os.environ.get("SIGMA_USERNAME")
    password = os.environ.get("SIGMA_PASSWORD")
    if not username or not password:
        return "Erro: defina SIGMA_USERNAME e SIGMA_PASSWORD no ambiente."
    try:
        sess = login(username, password)
    except Exception as e:
        return f"Login Sigma falhou: {e}"
    return f"Token Sigma: {sess['token'][:16]}… (B2: completo não vai pro transcript)"


def _sincronizar_sigma(o_que: str, paginas: int, per_page: int) -> str:
    if o_que not in (*SYNCERS, "all"):
        return f"'o_que' inválido: {o_que}. Opções: {', '.join([*SYNCERS, 'all'])}"
    try:
        with open_client() as client:
            if o_que == "all":
                results = sync_all(client, paginas, per_page)
            elif o_que == "customers":
                results = [sync_customers(client, paginas, per_page)]
            else:
                results = [SYNCERS[o_que](client)]
    except Exception as e:
        return f"Sync Sigma falhou: {e}"
    return json.dumps(results, ensure_ascii=False)


def _status_sigma() -> str:
    try:
        with open_client() as client:
            me = client.me()
    except Exception as e:
        return f"Sigma inacessível: {e}"
    return json.dumps(
        {
            "usuario": me.get("username"),
            "conta_expira_em": me.get("membership_expiry_date") or "ilimitado",
            "banco_local": entities_summary(),
        },
        ensure_ascii=False,
    )


def _listar_contas_sigma() -> str:
    accounts = load_accounts()
    if not accounts:
        return json.dumps(
            {"contas": [], "nota": "Nenhuma conta em sigma_accounts.json/env. "
             "Cadastre com: main.py sigma-account add NOME"},
            ensure_ascii=False,
        )
    active = resolve_active_account(accounts)
    return json.dumps(
        {
            "contas": [
                {
                    "username": a["username"],
                    "ativa": bool(active and a["username"] == active["username"]),
                    "sessao_salva": load_session(session_path_for(a["username"], accounts)) is not None,
                }
                for a in accounts
            ]
        },
        ensure_ascii=False,
    )


def _trocar_conta_sigma(username: str) -> str:
    accounts = load_accounts()
    if username not in {a["username"] for a in accounts}:
        return (f"Conta '{username}' não cadastrada. "
                f"Cadastre com: main.py sigma-account add {username}")
    set_last_good(username)
    try:
        with open_client() as client:
            me = client.me()
    except Exception as e:
        return (f"Ponteiro movido para {username}, mas a validação falhou "
                f"(sessão morta ou login demorou): {e}")
    return json.dumps(
        {"conta_ativa": username, "verificado_como": me.get("username")},
        ensure_ascii=False,
    )


def _criar_cliente_sigma(username, package_id, server_id, connections, password,
                         name, email, mostrar_senha=False) -> str:
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
        return f"Create falhou: {e}"
    cid = (res.get("data") or {}).get("id") if isinstance(res, dict) else None
    # M1: senha mascarada por padrão — igual ao CLI (--show-password)
    senha = pwd if mostrar_senha else pwd[:3] + "… (pedir mostrar_senha=True)"
    return json.dumps({"criado": username, "id": cid or "?", "senha": senha}, ensure_ascii=False)


def _editar_cliente_sigma(customer_id, note, add_days, set_expiry) -> str:
    if not (note or add_days or set_expiry):
        return "Nada a mudar: informe note, add_days e/ou set_expiry (YYYY-MM-DD)."
    try:
        with open_client() as client:
            row = find_customer(client, customer_id)
            if not row:
                return f"Cliente {customer_id} não encontrado."
            payload = dict(row)
            if note:
                payload["note"] = note
            new_exp = None
            if add_days or set_expiry:
                new_exp = customer_new_expiry(row, add_days, set_date=set_expiry)
                if not new_exp:
                    return "Row sem data de expiração — não dá para estender."
                set_expiry_on_payload(row, payload, new_exp)
            client.update_customer(customer_id, payload)
    except Exception as e:
        return f"Update falhou: {e}"
    return json.dumps({"id": customer_id, "nota": note, "expira": new_exp}, ensure_ascii=False)


def _excluir_cliente_sigma(customer_id, confirmar) -> str:
    if not confirmar:
        return "Exclusão exige confirmar=True (soft delete)."
    if not allow_destructive():
        return ("CR-10: exclusão exige SIGMA_ALLOW_DESTRUCTIVE=1 no ambiente "
                "(confirmar preenchido pelo próprio agente não é confirmação).")
    try:
        with open_client() as client:
            res = client.delete_customer(customer_id)
    except Exception as e:
        return f"Delete falhou: {e}"
    return json.dumps({"id": customer_id, "resposta": project_response(res)}, ensure_ascii=False)


def _resync_cliente_sigma(customer_id) -> str:
    try:
        with open_client() as client:
            res = client.resync_customer(customer_id)
    except Exception as e:
        return f"Resync falhou: {e}"
    # project_customer (não project_response): o resync devolve o row COMPLETO
    # com password/m3u_url — só os campos públicos podem vir pro transcript.
    return json.dumps({"id": customer_id, "cliente": project_customer(res)},
                      ensure_ascii=False)


def _listar_pacotes_sigma() -> str:
    try:
        with open_client() as client:
            sync_servers_packages(client)
    except Exception as e:
        return f"Sync de pacotes falhou: {e}"
    from core.database import list_entities as _list
    return json.dumps(
        {"servers": _list("server", limit=100),
         "packages": _list("package", limit=500)},
        ensure_ascii=False,
    )


def _buscar_cliente_sigma(termo: str, no_painel: bool) -> str:
    termo = (termo or "").strip()
    if not termo:
        return "Informe o termo de busca (username, nome, email ou id)."
    try:
        if no_painel:
            with open_client() as client:
                rows = search_customers(client, termo)
        else:
            rows = search_entities("customer", termo, limit=20)
    except Exception as e:
        return f"Busca falhou: {e}"
    return json.dumps(
        {"onde": "painel" if no_painel else "banco local",
         "total": len(rows),
         "clientes": [project_customer(r) for r in rows]},
        ensure_ascii=False,
    )


def _listar_clientes_sigma(pagina: int, por_pagina: int) -> str:
    try:
        rows = list_entities("customer", limit=max(1, min(por_pagina, 100)),
                             offset=(max(1, pagina) - 1) * max(1, por_pagina))
    except Exception as e:
        return f"Listagem falhou: {e}"
    return json.dumps(
        {"pagina": pagina, "total": len(rows),
         "clientes": [project_customer(r) for r in rows]},
        ensure_ascii=False,
    )


SyncWhat = Literal[
    "customers", "expiring", "dashboard", "resellers",
    "statistics", "servers_packages", "all",
]


def register(mcp):
    @mcp.tool()
    async def login_sigma() -> str:
        """
        Use quando: precisar de um login FRESCO no painel Sigma (as outras
        tools reutilizam a sessão salva sozinhas — raramente é preciso).

        Retorna: token mascarado (16 primeiros caracteres).

        Cuidados: usa SIGMA_USERNAME/SIGMA_PASSWORD; abre browser real e
        leva ~1min; não copie sigma_session.json entre máquinas (IP-bound).
        """
        return await anyio.to_thread.run_sync(_login_sigma)

    @mcp.tool()
    async def sincronizar_sigma(o_que: SyncWhat, paginas: int = 5, per_page: int = 100) -> str:
        """
        Use quando: quiser espelhar dados atuais do painel no banco local
        antes de consultar (equivalente CLI: sigma-sync --what).

        Retorna: JSON com resumo por dataset ({what, synced, pages, status}).

        Cuidados: somente leitura no painel; per_page cap 100 (a API ignora
        valores maiores); paginas só afeta customers.
        """
        return await anyio.to_thread.run_sync(_sincronizar_sigma, o_que, paginas, per_page)

    @mcp.tool()
    async def status_sigma() -> str:
        """
        Use quando: checar se o acesso ao Sigma está saudável antes de operar.

        Retorna: JSON {usuario, conta_expira_em, banco_local} — expiração da
        CONTA (membership; None = ilimitado) e contagem por dataset no banco.

        Cuidados: abre browser real (~10s com sessão válida); "conta_expira_em"
        NÃO é a expiração do painel inteiro (essa não é exposta pela API).
        """
        return await anyio.to_thread.run_sync(_status_sigma)

    # ---- gestão de clientes (mutações; 4 operações curated, sem bulk) ----------

    @mcp.tool()
    async def criar_cliente_sigma(
        username: str,
        package_id: str,
        server_id: str,
        connections: int = 1,
        password: str = None,
        name: str = None,
        email: str = None,
        mostrar_senha: bool = False,
    ) -> str:
        """
        Use quando: precisar CRIAR um cliente novo no painel.

        Retorna: JSON {criado, id, senha} — senha mascarada por padrão
        (mostrar_senha=True exibe em claro; CLI equivale: --show-password).

        Cuidados: MUTAÇÃO (cria no painel real). Use listar_pacotes_sigma
        para achar o par package_id/server_id coerente — pacote de outro
        servidor dá 400. Senha: só letras/números/-/@/_ (auto-gerada segura).
        Paridade CLI: sigma-customer-create.
        """
        return await anyio.to_thread.run_sync(
            _criar_cliente_sigma, username, package_id, server_id,
            connections, password, name, email, mostrar_senha,
        )

    @mcp.tool()
    async def editar_cliente_sigma(
        customer_id: str, note: str = None, add_days: int = 0, set_expiry: str = None
    ) -> str:
        """
        Use quando: precisar mudar nota e/ou expiração de um cliente.

        Retorna: JSON {id, nota, expira} — expiração calculada (YYYY-MM-DD).

        Cuidados: MUTAÇÃO (edita no painel real). add_days conta da data
        atual do cliente; set_expiry "YYYY-MM-DD" fixa direto; ao menos um
        dos três obrigatório. Paridade CLI: sigma-customer-update
        (--note/--add-days/--set-expiry).
        """
        return await anyio.to_thread.run_sync(
            _editar_cliente_sigma, customer_id, note, add_days, set_expiry
        )

    @mcp.tool()
    async def excluir_cliente_sigma(customer_id: str, confirmar: bool = False) -> str:
        """
        Use quando: o DONO pediu explicitamente a remoção de um cliente.

        Retorna: JSON {id, resposta} com campos seguros (id/deleted_at/status).

        Cuidados: DESTRUTIVO mas é SOFT delete (restaurável no painel).
        Exige confirmar=True E o env SIGMA_ALLOW_DESTRUCTIVE=1 — confirmar
        preenchido pelo próprio agente não é confirmação (CR-10).
        Paridade CLI: sigma-customer-delete ID --yes (mesmo gate de env).
        """
        return await anyio.to_thread.run_sync(_excluir_cliente_sigma, customer_id, confirmar)

    @mcp.tool()
    async def resync_cliente_sigma(customer_id: str) -> str:
        """
        Use quando: cliente diz que atualizou a lista no app e não vê os
        canais novos — força o painel reenviar a configuração ao servidor IPTV.

        Retorna: JSON {id, cliente} com apenas campos públicos (username,
        status, expires_at, note…) — NUNCA senha/m3u_url, que embutem senha.

        Cuidados: mutação inofensiva (não altera dados, só sincroniza).
        Paridade CLI: sigma-customer-resync.
        """
        return await anyio.to_thread.run_sync(_resync_cliente_sigma, customer_id)

    # ---- consulta (leitura) -----------------------------------------------------

    @mcp.tool()
    async def listar_pacotes_sigma() -> str:
        """
        Use quando: for criar/editar cliente e precisar dos IDs de pacote e
        servidor (o par precisa ser coerente).

        Retorna: JSON {servers: [...], packages: [...]} com name, server_id,
        preço etc. — dados de catálogo, sem PII.

        Cuidados: sincroniza o catálogo do painel antes de listar (2 GETs);
        catálogo grande (~128 pacotes). Paridade CLI: sigma-servers-packages.
        """
        return await anyio.to_thread.run_sync(_listar_pacotes_sigma)

    @mcp.tool()
    async def listar_contas_sigma() -> str:
        """
        Use quando: precisar saber quais contas do painel Sigma estão
        cadastradas, qual está ativa e qual tem sessão salva.

        Retorna: JSON {contas: [{username, ativa, sessao_salva}]} — NUNCA
        senhas.

        Cuidados: leitura local (sem browser, instantâneo). A ativa segue a
        resolução SIGMA_ACCOUNT > ponteiro > primeira do arquivo. Paridade
        CLI: sigma-account list.
        """
        return await anyio.to_thread.run_sync(_listar_contas_sigma)

    @mcp.tool()
    async def trocar_conta_sigma(username: str) -> str:
        """
        Use quando: o DONO pedir explicitamente operar com outra conta
        cadastrada.

        Retorna: JSON {conta_ativa, verificado_como} após validar /api/auth/me
        no painel.

        Cuidados: muda o ponteiro GLOBAL (afeta cron e outros processos);
        se a conta não tiver sessão salva, dispara login no browser
        (~1min). Nunca peça nem repasse senhas — cadastro é via CLI
        sigma-account add. Paridade CLI: sigma-account use.
        """
        return await anyio.to_thread.run_sync(_trocar_conta_sigma, username)

    @mcp.tool()
    async def buscar_cliente_sigma(termo: str, no_painel: bool = False) -> str:
        """
        Use quando: tiver parte do username/nome/email/id e precisar do
        cliente completo (ex.: id antes de editar/excluir).

        Retorna: JSON {onde, total, clientes:[...]} — só campos públicos.

        Cuidados: padrão busca no BANCO LOCAL (rápido; dados da última
        sincronização — rode sincronizar_sigma antes se estiver velho).
        no_painel=True consulta ao vivo (lento: pagina a lista toda).
        Paridade CLI: grep em sigma-sync + consultas locais.
        """
        return await anyio.to_thread.run_sync(_buscar_cliente_sigma, termo, no_painel)

    @mcp.tool()
    async def listar_clientes_sigma(pagina: int = 1, por_pagina: int = 20) -> str:
        """
        Use quando: quiser folhear a base local de clientes (recentes primeiro).

        Retorna: JSON {pagina, total, clientes:[...]} — só campos públicos.

        Cuidados: lê o BANCO LOCAL (não o painel); por_pagina cap 100;
        rode sincronizar_sigma('customers') antes para dados atuais.
        """
        return await anyio.to_thread.run_sync(
            _listar_clientes_sigma, pagina, por_pagina
        )
