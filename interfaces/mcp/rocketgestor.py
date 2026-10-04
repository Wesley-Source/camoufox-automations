"""Tools MCP do Rocket Gestor (Django server-rendered, cookies — NÃO-sigma).

Política do painel: créditos INEXISTENTES → criar/alterar/deletar CLIENTE DE
TESTE (zz_test_*) é livre; clientes REAIS intocados sem aprovação do dono.
"""
import json
import os

import anyio

from core.database import count_entities
from core.rocketgestor.api import open_client
from core.rocketgestor.auth import (
    ensure_logged_page,
    load_accounts,
    load_session,
    resolve_active_account,
    save_session,
)


# ---- implementações síncronas (CR-01: browser fora do event loop) -----------


def _login_rocketgestor(user: str = None) -> str:
    accounts = load_accounts()
    if user:
        acc = next((a for a in accounts if a["username"] == user), None)
        if not acc:
            return f"Conta {user} não está em rocketgestor_accounts.json."
    elif accounts:
        acc = resolve_active_account(accounts)
    else:
        acc = {"username": os.environ.get("SIGMA_USERNAME", ""),
               "password": os.environ.get("SIGMA_PASSWORD", "")}
    try:
        with ensure_logged_page(username=acc["username"], password=acc["password"]) as s:
            save_session(s.page, username=acc["username"])
        return f"Login rocketgestor OK: {acc['username']} (sessão salva)."
    except Exception as e:
        return f"Login rocketgestor falhou: {e} — confirme a senha antes de repetir (ban counter)."


def _status_rocketgestor() -> str:
    accounts = load_accounts()
    active = resolve_active_account(accounts) if accounts else None
    sess = load_session() is not None
    try:
        n = count_entities("rocketgestor.client")
    except Exception:
        n = 0
    return json.dumps(
        {"conta_ativa": active["username"] if active else None,
         "sessao_salva": sess,
         "clientes_no_banco": n},
        ensure_ascii=False)


def _sincronizar_rocketgestor(status: str, paginas: int) -> str:
    try:
        with open_client() as client:
            res = client.sync_clients(status or None, max_pages=paginas)
        return json.dumps({"synced": res.get("synced", res.get("pages")),
                           "status": status or "todos"}, ensure_ascii=False)
    except Exception as e:
        return f"Sync rocketgestor falhou: {e}"


def _listar_rocketgestor(status: str, paginas: int) -> str:
    try:
        with open_client() as client:
            rows = client.list_clients(status or None, max_pages=paginas)
        return json.dumps({"total": len(rows), "clientes": rows}, ensure_ascii=False)
    except Exception as e:
        return f"Listagem falhou: {e}"


def _buscar_rocketgestor(termo: str) -> str:
    try:
        with open_client() as client:
            rows = client.find_client(termo)
        return json.dumps({"total": len(rows), "clientes": rows}, ensure_ascii=False)
    except Exception as e:
        return f"Busca falhou: {e}"


def _criar_rocketgestor(nome, usuario, vencimento, plano, valor, forma,
                        telas, senha, telefone) -> str:
    payload = {"nome": nome, "usuario": usuario, "vencimento": vencimento,
               "plano": plano, "valor": float(valor), "forma_de_pagamento": forma,
               "telas": int(telas)}
    if senha:
        payload["senha"] = senha
    if telefone:
        payload["telefone_1"] = telefone
    try:
        with open_client() as client:
            res = client.create_client(payload)
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return f"Criação falhou: {e}"


def _editar_rocketgestor(customer_id, vencimento, valor, plano, forma, telas) -> str:
    overrides = {}
    if vencimento:
        overrides["vencimento"] = vencimento
    if valor:
        overrides["valor"] = float(valor)
    if plano:
        overrides["plano"] = plano
    if forma:
        overrides["forma_de_pagamento"] = forma
    if telas:
        overrides["telas"] = int(telas)
    try:
        with open_client() as client:
            res = client.update_client(str(customer_id), overrides)
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return f"Edição falhou: {e}"


def _apagar_rocketgestor(customer_id, confirmar) -> str:
    if not confirmar:
        return "Exclusão exige confirmar=True (soft delete → lixeira, restaurável)."
    if os.environ.get("SIGMA_ALLOW_DESTRUCTIVE") != "1":
        return "Gate destrutivo fechado: defina SIGMA_ALLOW_DESTRUCTIVE=1."
    try:
        with open_client() as client:
            res = client.delete_client(str(customer_id))
        return json.dumps(res, ensure_ascii=False)
    except Exception as e:
        return f"Exclusão falhou: {e}"


def register(mcp):
    @mcp.tool()
    async def login_rocketgestor(user: str = "") -> str:
        """
        Use quando: a sessão do Rocket Gestor morreu e as tools falham com
        erro de sessão. Prefere contas de rocketgestor_accounts.json.

        Retorna: confirmação do login (ou erro — confirme a senha antes de
        repetir; o form de login pode contar tentativas).

        Cuidados: mutação leve (cria sessão); abre browser real (~1min).
        """
        return await anyio.to_thread.run_sync(_login_rocketgestor, user or None)

    @mcp.tool()
    async def status_rocketgestor() -> str:
        """
        Use quando: checar acesso ao Rocket Gestor e o tamanho do espelho
        local antes de operar.

        Retorna: JSON {conta_ativa, sessao_salva, clientes_no_banco}.
        """
        return await anyio.to_thread.run_sync(_status_rocketgestor)

    @mcp.tool()
    async def sincronizar_rocketgestor(status: str = "", paginas: int = 10) -> str:
        """
        Use quando: quiser espelhar clientes do painel no banco local
        (kinds rocketgestor.client) antes de consultas offline.

        Retorna: JSON {synced, status}. Cuidados: leitura; status opcional
        (Ativo/Vencido/'Vence Hoje').
        """
        return await anyio.to_thread.run_sync(_sincronizar_rocketgestor, status, paginas)

    @mcp.tool()
    async def listar_clientes_rocketgestor(status: str = "", paginas: int = 1) -> str:
        """
        Use quando: folhear os clientes do Rocket Gestor ao vivo.

        Retorna: JSON {total, clientes:[{id, uuid, nome, login, telefone,
        vencimento, plano, valor, status, ...}]} — inclui login IPTV.

        Cuidados: cada página é um GET de ~1.4MB; comece com paginas=1.
        """
        return await anyio.to_thread.run_sync(_listar_rocketgestor, status, paginas)

    @mcp.tool()
    async def buscar_cliente_rocketgestor(termo: str) -> str:
        """
        Use quando: tiver parte do nome/login/telefone/id de um cliente do
        Rocket Gestor.

        Retorna: JSON {total, clientes:[...]} com login IPTV em claro.
        """
        return await anyio.to_thread.run_sync(_buscar_rocketgestor, termo)

    @mcp.tool()
    async def criar_cliente_rocketgestor(nome: str, usuario: str, vencimento: str,
                                         plano: str = "Mensal", valor: float = 30.0,
                                         forma_de_pagamento: str = "Pix", telas: int = 1,
                                         senha: str = "", telefone: str = "") -> str:
        """
        Use quando: precisar criar um cliente NO PAINEL Rocket Gestor.

        Retorna: JSON {ok, status, username, alert}.

        Cuidados: vencimento dd/mm/aaaa; plano e forma aceitam TEXTO
        ('Mensal', 'Pix' — mapeados p/ ID numérico); prefira usuários
        zz_test_* (política do painel: testes livres, reais intocados).
        Paridade CLI: rocketgestor-criar.
        """
        return await anyio.to_thread.run_sync(
            _criar_rocketgestor, nome, usuario, vencimento, plano, valor,
            forma_de_pagamento, telas, senha, telefone)

    @mcp.tool()
    async def editar_cliente_rocketgestor(customer_id: str, vencimento: str = "",
                                          valor: float = 0, plano: str = "",
                                          forma_de_pagamento: str = "",
                                          telas: int = 0) -> str:
        """
        Use quando: precisar mudar vencimento/valor/plano/forma/telas de um
        cliente do Rocket Gestor (o id numérico vem de listar/buscar).

        Retorna: JSON {ok, id, status, alert} — alert honesto se o painel
        rejeitar.

        Cuidados: vencimento ISO (aaaa-mm-dd); forma_de_pagamento é
        OBRIGATÓRIA pelo painel em toda edição (texto mapeado p/ ID);
        passe ao menos um campo. Paridade CLI: rocketgestor-editar.
        """
        return await anyio.to_thread.run_sync(
            _editar_rocketgestor, str(customer_id), vencimento, valor, plano,
            forma_de_pagamento, telas)

    @mcp.tool()
    async def apagar_cliente_rocketgestor(customer_id: str, confirmar: bool = False) -> str:
        """
        Use quando: o DONO pedir explicitamente remover um cliente do Rocket
        Gestor.

        Retorna: JSON {ok, id, uuid, note} — soft delete → lixeira
        (restaurável no painel).

        Cuidados: DESTRUTIVO — exige confirmar=True E SIGMA_ALLOW_
        DESTRUCTIVE=1 no ambiente. Exceção de política: clientes zz_test_*
        podem ser apagados livremente (créditos inexistentes), mas o gate
        continua valendo. Paridade CLI: rocketgestor-apagar ID --yes.
        """
        return await anyio.to_thread.run_sync(
            _apagar_rocketgestor, str(customer_id), confirmar)
