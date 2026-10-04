"""Playlist do cliente — dados da aba Playlist (credenciais IPTV em claro).

DECISÃO DO DONO (03/10/2026): o atendente precisa ver usuário/senha IPTV e
m3u_url de cada cliente nesta tool — EXCEÇÃO DOCUMENTADA da regra 5
(AGENTS.md). `project_*` continua filtrando em buscas/listagens em massa.
"""
import json
from typing import Literal

import anyio

from core.blackbr import api as _blackbr
from core.newmais import api as _newmais
from core.sigma import api as _sigma
from core.woodcine import api as _woodcine


# painel → módulo de API do site (todos expõem open_client/find_customer)
SITES = {
    "sigma": _sigma,
    "woodcine": _woodcine,
    "blackbr": _blackbr,
    "newmais": _newmais,
}

SecretFields = ("password", "m3u_url", "renew_url")


def _playlist_cliente_impl(painel: str, customer_id: str, mascarar: bool = False) -> str:
    mod = SITES.get(painel)
    if mod is None:
        return f"Painel inválido: {painel}. Opções: {', '.join(SITES)}."
    cid = (customer_id or "").strip()
    if not cid:
        return "Informe o ID do cliente."
    try:
        with mod.open_client() as client:
            row = mod.find_customer(client, cid)
            if not row:
                return (f"Cliente {cid} não encontrado no painel {painel} "
                        f"(rode <painel>-sync primeiro ou confira o ID).")
            out = {
                "id": row.get("id"),
                "username": row.get("username"),
                "password": row.get("password"),
                "m3u_url": row.get("m3u_url"),
                "status": row.get("status"),
                "expiry_date": row.get("expiry_date") or row.get("expires_at"),
            }
            try:
                extras = client.customer_playlist(cid)
                # Templates por idioma (mensagem fallback quando o admin não
                # configurou template p/ o servidor) — inclui só se houver
                # conteúdo além do fallback.
                real = [e for e in (extras if isinstance(extras, list) else [])
                        if isinstance(e, dict) and "template" not in e]
                if real:
                    out["playlist_templates"] = real
            except Exception:
                pass  # playlist é acessório; credenciais do row bastam
        if mascarar:
            for f in SecretFields:
                if out.get(f):
                    out[f] = str(out[f])[:4] + "…"
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return f"Playlist falhou ({painel}): {e}"


def register(mcp):
    @mcp.tool()
    async def playlist_cliente(painel: Literal["sigma", "woodcine", "blackbr", "newmais"],
                               customer_id: str, mascarar: bool = False) -> str:
        """
        Use quando: o CLIENTE pedir os próprios dados IPTV (usuário/senha e
        link m3u) ou quais apps baixar — atende sem abrir o painel.

        Retorna: JSON {id, username, password, m3u_url, status, expiry_date}
        — credenciais EM CLARO POR DECISÃO DO DONO (exceção da regra 5).

        Cuidados: consulta 1 painel por chamada; `mascarar=True` esconde
        password/m3u_url se a conversa for pública. Paridade CLI:
        <painel>-customer-playlist ID [--mascarar].
        """
        return await anyio.to_thread.run_sync(
            _playlist_cliente_impl, painel, customer_id, mascarar
        )
