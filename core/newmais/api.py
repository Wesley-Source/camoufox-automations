"""Cliente da API do painel Newmais — config + re-exports do base.

Toda a lógica vive em core/panel_api.py (AGENTS.md G5: correção vai no
BASE, não nas cópias).
"""
import sys
from contextlib import contextmanager

import requests
import time

from core.panel_api import (
    _BrowserTransport,
    _DOH_TTL,
    _is_dns_failure,
    CUSTOMER_PUBLIC_FIELDS,
    PanelApiClient,
    PanelApiError,
    customer_new_expiry,
    doh_resolve,
    find_customer,
    open_client_for,
    project_customer,
    project_response,
    search_customers,
    set_expiry_on_payload,
)
from core.newmais.auth import (
    NEWMAIS_API,
    NEWMAIS_URL,
    NEWMAIS_SESSION_FILE,
    default_proxy,
    ensure_logged_page,
    load_session,
)

NEWMAIS_HOST = NEWMAIS_URL.replace("https://", "")


class NewmaisApiError(PanelApiError):
    def __init__(self, path: str, status: int, body: str):
        super().__init__(path, status, body, vendor="Newmais")


class NewmaisApiClient(PanelApiClient):
    """GET-only na API do Newmais com token de newmais_session.json.

    `transport=None` usa requests (motor de teste; CF bloqueia em produção).
    Produção: use `open_client()`, que injeta o transporte do browser.
    """

    API_BASE = NEWMAIS_API
    HOST = NEWMAIS_HOST
    VENDOR = "newmais"
    API_ERROR = NewmaisApiError
    DEFAULT_SESSION_FILE = NEWMAIS_SESSION_FILE
    _AUTH = sys.modules[__name__]


@contextmanager
def open_client(session_path: str = NEWMAIS_SESSION_FILE, proxy: str = None, guard=None):
    """
    Cliente com transporte do browser (o único que o Cloudflare aceita).

    Abre o browser com a sessão salva (reutiliza se válida, senão refaz
    login) e devolve o client. session_path: default NEWMAIS_SESSION_FILE,
    ancorado em __file__ (A1: default relativo quebrava cron/CWD≠raiz).
    """
    with open_client_for(NewmaisApiClient, session_path, proxy, guard) as c:
        yield c
