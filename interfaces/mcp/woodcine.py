import json
import os
from typing import Literal

import anyio

from core.woodcine.api import open_client, project_customer, search_customers
from core.database import list_entities, search_entities
from core.woodcine.auth import (
    load_accounts,
    load_session,
    login,
    resolve_active_account,
    session_path_for,
    set_last_good,
)
from core.woodcine.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
    sync_servers_packages,
)


# ---- implementações síncronas (CR-01: browser/Playwright fora do event loop) --


def _login_woodcine() -> str:
    username = os.environ.get("SIGMA_USERNAME")
    password = os.environ.get("SIGMA_PASSWORD")
    if not username or not password:
        return "Erro: defina SIGMA_USERNAME e SIGMA_PASSWORD no ambiente (ou --user via CLI)."
    try:
        sess = login(username, password)
    except Exception as e:
        return f"Login woodcine falhou: {e}"
    return f"Token woodcine: {sess['token'][:16]}… (completo não vai pro transcript)"


def _sincronizar_woodcine(o_que: str, paginas: int, per_page: int) -> str:
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
        return f"Sync woodcine falhou: {e}"
    return json.dumps(results, ensure_ascii=False)


def _status_woodcine() -> str:
    try:
        with open_client() as client:
            me = client.me()
    except Exception as e:
        return f"Woodcine inacessível: {e}"
    accounts = load_accounts()
    active = resolve_active_account(accounts) if accounts else None
    return json.dumps(
        {
            "usuario": me.get("username"),
            "conta_ativa": active["username"] if active else None,
            "conta_expira_em": me.get("membership_expiry_date") or "ilimitado",
            "banco_local": entities_summary(),
        },
        ensure_ascii=False,
    )


def _listar_contas_woodcine() -> str:
    accounts = load_accounts()
    if not accounts:
        return json.dumps(
            {"contas": [], "nota": "Nenhuma conta em woodcine_accounts.json/env. "
             "Cadastre com: main.py woodcine-account add NOME"},
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


def _trocar_conta_woodcine(username: str) -> str:
    accounts = load_accounts()
    if username not in {a["username"] for a in accounts}:
        return (f"Conta '{username}' não cadastrada. "
                f"Cadastre com: main.py woodcine-account add {username}")
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


def _listar_pacotes_woodcine() -> str:
    try:
        with open_client() as client:
            sync_servers_packages(client)
    except Exception as e:
        return f"Sync de pacotes falhou: {e}"
    return json.dumps(
        {"servers": list_entities("woodcine.server", limit=100),
         "packages": list_entities("woodcine.package", limit=500)},
        ensure_ascii=False,
    )


def _buscar_cliente_woodcine(termo: str, no_painel: bool) -> str:
    termo = (termo or "").strip()
    if not termo:
        return "Informe o termo de busca (username, nome, email ou id)."
    try:
        if no_painel:
            with open_client() as client:
                rows = search_customers(client, termo)
        else:
            rows = search_entities("woodcine.customer", termo, limit=20)
    except Exception as e:
        return f"Busca falhou: {e}"
    return json.dumps(
        {"onde": "painel" if no_painel else "banco local",
         "total": len(rows),
         "clientes": [project_customer(r) for r in rows]},
        ensure_ascii=False,
    )


def _listar_clientes_woodcine(pagina: int, por_pagina: int) -> str:
    try:
        rows = list_entities("woodcine.customer", limit=max(1, min(por_pagina, 100)),
                             offset=(max(1, pagina) - 1) * max(1, por_pagina))
    except Exception as e:
        return f"Listagem falhou: {e}"
    return json.dumps(
        {"pagina": pagina, "total": len(rows),
         "clientes": [project_customer(r) for r in rows]},
        ensure_ascii=False,
    )


WoodcineSyncWhat = Literal[
    "customers", "expiring", "dashboard", "resellers",
    "statistics", "servers_packages", "all",
]


def register(mcp):
    @mcp.tool()
    async def login_woodcine() -> str:
        """
        Use quando: precisar de um login FRESCO no painel woodcine
        (woodcine.sigma.st — as outras tools reutilizam a sessão salva).

        Retorna: token mascarado (16 primeiros caracteres).

        Cuidados: usa SIGMA_USERNAME/SIGMA_PASSWORD; abre browser real e
        leva ~1min; não copie woodcine_session.json entre máquinas.
        """
        return await anyio.to_thread.run_sync(_login_woodcine)

    @mcp.tool()
    async def sincronizar_woodcine(o_que: WoodcineSyncWhat, paginas: int = 5, per_page: int = 100) -> str:
        """
        Use quando: quiser espelhar dados do painel woodcine no banco local
        antes de consultar (grava com prefixo woodcine.* — não mistura com
        o lideriptv). Equivalente CLI: woodcine-sync --what.

        Retorna: JSON com resumo por dataset ({what, synced, pages, status}).

        Cuidados: somente leitura no painel; per_page cap 100; paginas só
        afeta customers.
        """
        return await anyio.to_thread.run_sync(_sincronizar_woodcine, o_que, paginas, per_page)

    @mcp.tool()
    async def status_woodcine() -> str:
        """
        Use quando: checar se o acesso ao woodcine está saudável antes de operar.

        Retorna: JSON {usuario, conta_ativa, conta_expira_em, banco_local}.

        Cuidados: abre browser real (~10s com sessão válida); conta_expira_em
        é da CONTA (membership), não do painel inteiro.
        """
        return await anyio.to_thread.run_sync(_status_woodcine)

    @mcp.tool()
    async def listar_contas_woodcine() -> str:
        """
        Use quando: precisar saber quais contas do woodcine estão
        cadastradas, qual está ativa e qual tem sessão salva.

        Retorna: JSON {contas: [{username, ativa, sessao_salva}]} — NUNCA
        senhas.

        Cuidados: leitura local (instantâneo). Ativa segue SIGMA_ACCOUNT >
        ponteiro .woodcine_last_good > primeira do arquivo. Paridade CLI:
        woodcine-account list.
        """
        return await anyio.to_thread.run_sync(_listar_contas_woodcine)

    @mcp.tool()
    async def trocar_conta_woodcine(username: str) -> str:
        """
        Use quando: o DONO pedir explicitamente operar o woodcine com outra
        conta cadastrada.

        Retorna: JSON {conta_ativa, verificado_como} após validar
        /api/auth/me no painel.

        Cuidados: muda o ponteiro GLOBAL do woodcine; se a conta não tiver
        sessão salva, dispara login no browser (~1min). Nunca repasse
        senhas. Paridade CLI: woodcine-account use.
        """
        return await anyio.to_thread.run_sync(_trocar_conta_woodcine, username)

    @mcp.tool()
    async def listar_pacotes_woodcine() -> str:
        """
        Use quando: for criar/editar cliente no woodcine e precisar dos IDs
        de pacote e servidor (o par precisa ser coerente).

        Retorna: JSON {servers: [...], packages: [...]} — catálogo, sem PII.

        Cuidados: sincroniza o catálogo antes de listar (2 GETs); kinds
        woodcine.server/woodcine.package no banco. Paridade CLI:
        woodcine-servers-packages.
        """
        return await anyio.to_thread.run_sync(_listar_pacotes_woodcine)

    @mcp.tool()
    async def buscar_cliente_woodcine(termo: str, no_painel: bool = False) -> str:
        """
        Use quando: tiver parte do username/nome/email/id de um cliente do
        woodcine e precisar do registro completo.

        Retorna: JSON {onde, total, clientes:[...]} — só campos públicos.

        Cuidados: padrão busca no BANCO LOCAL (dados do último
        sincronizar_woodcine); no_painel=True consulta ao vivo (lento).
        """
        return await anyio.to_thread.run_sync(_buscar_cliente_woodcine, termo, no_painel)

    @mcp.tool()
    async def listar_clientes_woodcine(pagina: int = 1, por_pagina: int = 20) -> str:
        """
        Use quando: quiser folhear a base local de clientes do woodcine.

        Retorna: JSON {pagina, total, clientes:[...]} — só campos públicos.

        Cuidados: lê o BANCO LOCAL; por_pagina cap 100; rode
        sincronizar_woodcine('customers') antes para dados atuais.
        """
        return await anyio.to_thread.run_sync(_listar_clientes_woodcine, pagina, por_pagina)
