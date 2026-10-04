"""Tools MCP do painel blackbr — spec + engine compartilhado (_panel.py).

Os workers `_op_blackbr` são partials do engine com ESTE módulo como 1º
arg (mesma assinatura pública de sempre — testes importam e chamam igual).
Tests fazem monkeypatch AQUI (ex. load_accounts/load_session/...); o
engine lê via getattr no call time.
"""
import sys
from functools import partial
from typing import Literal

from core.blackbr.api import (
    customer_new_expiry,
    find_customer,
    open_client,
    project_customer,
    project_response,
    search_customers,
    set_expiry_on_payload,
)
from core.blackbr.auth import (
    allow_destructive,
    load_accounts,
    load_session,
    login,
    resolve_active_account,
    session_path_for,
    set_last_good,
)
from core.blackbr.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
    sync_servers_packages,
)
from core.database import list_entities, search_entities

from interfaces.mcp import _panel

SITE = "blackbr"
DISPLAY = "Blackbr"
URL = "https://painelblackbr.com"
KIND = "blackbr"
SyncWhat = Literal[tuple([*SYNCERS, "all"])]

_SPEC = sys.modules[__name__]

_login_blackbr = partial(_panel.login_worker, _SPEC)
_sincronizar_blackbr = partial(_panel.sincronizar_worker, _SPEC)
_status_blackbr = partial(_panel.status_worker, _SPEC)
_listar_contas_blackbr = partial(_panel.listar_contas_worker, _SPEC)
_trocar_conta_blackbr = partial(_panel.trocar_conta_worker, _SPEC)
_listar_pacotes_blackbr = partial(_panel.listar_pacotes_worker, _SPEC)
_buscar_cliente_blackbr = partial(_panel.buscar_cliente_worker, _SPEC)
_listar_clientes_blackbr = partial(_panel.listar_clientes_worker, _SPEC)
_criar_cliente_blackbr = partial(_panel.criar_cliente_worker, _SPEC)
_editar_cliente_blackbr = partial(_panel.editar_cliente_worker, _SPEC)
_excluir_cliente_blackbr = partial(_panel.excluir_cliente_worker, _SPEC)
_resync_cliente_blackbr = partial(_panel.resync_cliente_worker, _SPEC)


def register(mcp):
    _panel.register_panel(mcp, _SPEC)
