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
from core.sigma.auth import allow_destructive, login
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
        Faz login no painel Sigma (https://lideriptv.sigma.st) e retorna o token de acesso.
        Usa as variáveis de ambiente SIGMA_USERNAME e SIGMA_PASSWORD.
        """
        return await anyio.to_thread.run_sync(_login_sigma)

    @mcp.tool()
    async def sincronizar_sigma(o_que: SyncWhat, paginas: int = 5, per_page: int = 100) -> str:
        """
        Sincroniza dados do painel Sigma para o banco local (somente leitura).
        Equivalente MCP de `sigma-sync --what` (CLI).
        paginas: páginas de clientes quando aplicável; per_page: linhas por página (cap 100).
        """
        return await anyio.to_thread.run_sync(_sincronizar_sigma, o_que, paginas, per_page)

    @mcp.tool()
    async def status_sigma() -> str:
        """
        Valide o acesso ao painel Sigma: usuário, expiração do painel
        (None = ilimitado) e contagem de entidades no banco local.
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
        Cria um cliente no painel Sigma. package_id e server_id são IDs string
        do painel (ex.: rdqLkQjWAE) e devem formar par coerente (o pacote
        pertence ao servidor). Senha gerada se não informada e mascarada no
        resultado — passe mostrar_senha=True para vê-la em claro (M1).
        name/email padrão derivados do username.
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
        Edita um cliente do painel Sigma: altera a nota e/ou define a expiração
        (add_days dias a partir da atual, ou set_expiry "YYYY-MM-DD" direto).
        Ao menos um dos três deve ser informado.
        """
        return await anyio.to_thread.run_sync(
            _editar_cliente_sigma, customer_id, note, add_days, set_expiry
        )

    @mcp.tool()
    async def excluir_cliente_sigma(customer_id: str, confirmar: bool = False) -> str:
        """
        Remove um cliente do painel Sigma (SOFT delete, restaurável).
        DESTRUTIVO: exige confirmar=True além do ID correto.
        """
        return await anyio.to_thread.run_sync(_excluir_cliente_sigma, customer_id, confirmar)

    @mcp.tool()
    async def resync_cliente_sigma(customer_id: str) -> str:
        """Força o resync do cliente no servidor IPTV do painel Sigma.
        Retorna só campos públicos do cliente (nunca senha/m3u_url)."""
        return await anyio.to_thread.run_sync(_resync_cliente_sigma, customer_id)

    # ---- consulta (leitura) -----------------------------------------------------

    @mcp.tool()
    async def listar_pacotes_sigma() -> str:
        """
        Lista servidores e pacotes do painel Sigma (sincroniza primeiro).
        Use para achar o par package_id/server_id coerente antes de
        criar um cliente (o pacote pertence a um servidor).
        """
        return await anyio.to_thread.run_sync(_listar_pacotes_sigma)

    @mcp.tool()
    async def buscar_cliente_sigma(termo: str, no_painel: bool = False) -> str:
        """
        Busca clientes por parte do username, nome, email ou id.
        Padrão consulta o banco local (rápido, última sincronização);
        no_painel=True consulta o painel ao vivo (mais lento, dados atuais).
        Retorna apenas campos públicos.
        """
        return await anyio.to_thread.run_sync(_buscar_cliente_sigma, termo, no_painel)

    @mcp.tool()
    async def listar_clientes_sigma(pagina: int = 1, por_pagina: int = 20) -> str:
        """
        Lista clientes do banco local (mais recentemente sincronizados primeiro).
        por_pagina cap 100. Use sincronizar_sigma('customers') antes para atualizar.
        """
        return await anyio.to_thread.run_sync(
            _listar_clientes_sigma, pagina, por_pagina
        )
