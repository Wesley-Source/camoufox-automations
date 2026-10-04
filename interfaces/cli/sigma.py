"""CLI do painel sigma (lideriptv) — spec + engine compartilhado (_panel.py).

Este módulo é o contrato do engine: constantes do site + reexport dos
nomes de core.* (tests fazem monkeypatch AQUI — ex. load_accounts/login/
SESSION_FILE; o engine lê via getattr no call time).
KIND=None: o sigma é o painel original — kinds no banco SEM prefixo.
"""
import sys

from core.sigma.auth import (
    ACCOUNTS_FILE,
    SESSION_FILE,
    allow_destructive,
    load_accounts,
    load_session,
    login,
    resolve_active_account,
    save_session,
    session_path_for,
    set_last_good,
)
from core.sigma.api import (
    customer_new_expiry,
    find_customer,
    open_client,
    project_customer,
    project_response,
    set_expiry_on_payload,
)
from core.sigma.scraper import (
    SYNCERS,
    entities_summary,
    sync_all,
    sync_customers,
    sync_servers_packages,
)
from core.database import list_entities

from interfaces.cli import _panel

SITE = "sigma"
DISPLAY = "Sigma"
URL = "https://lideriptv.sigma.st"
KIND = None

_SPEC = sys.modules[__name__]


def register(app):
    _panel.register_panel(app, _SPEC)
