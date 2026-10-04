"""CLI do painel blackbr — spec + engine compartilhado (_panel.py).

Este módulo é o contrato do engine: constantes do site + reexport dos
nomes de core.* (tests fazem monkeypatch AQUI — ex. load_accounts/login/
SESSION_FILE; o engine lê via getattr no call time).
"""
import sys

from core.blackbr.auth import (
    BLACKBR_ACCOUNTS_FILE as ACCOUNTS_FILE,
    BLACKBR_SESSION_FILE as SESSION_FILE,
    allow_destructive,
    load_accounts,
    load_session,
    login,
    resolve_active_account,
    save_session,
    session_path_for,
    set_last_good,
)
from core.blackbr.api import (
    customer_new_expiry,
    find_customer,
    open_client,
    project_customer,
    project_response,
    set_expiry_on_payload,
)
from core.blackbr.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
    sync_servers_packages,
)
from core.database import list_entities

from interfaces.cli import _panel

SITE = "blackbr"
DISPLAY = "Blackbr"
URL = "https://painelblackbr.com"
KIND = "blackbr"

_SPEC = sys.modules[__name__]


def register(app):
    _panel.register_panel(app, _SPEC)
