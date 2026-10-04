"""CLI do painel newmais — spec + engine compartilhado (_panel.py).

Este módulo é o contrato do engine: constantes do site + reexport dos
nomes de core.* (tests fazem monkeypatch AQUI — ex. load_accounts/login/
SESSION_FILE; o engine lê via getattr no call time).
"""
import sys

from core.newmais.auth import (
    NEWMAIS_ACCOUNTS_FILE as ACCOUNTS_FILE,
    NEWMAIS_SESSION_FILE as SESSION_FILE,
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
from core.newmais.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
    sync_servers_packages,
)
from core.database import list_entities

from interfaces.cli import _panel

SITE = "newmais"
DISPLAY = "Newmais"
URL = "https://newmais.sigma.vin"
KIND = "newmais"

_SPEC = sys.modules[__name__]


def register(app):
    _panel.register_panel(app, _SPEC)
