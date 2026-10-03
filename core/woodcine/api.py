"""Cliente da API do painel Woodcine — config + re-exports do base.

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
from core.woodcine.auth import (
    WOODCINE_API,
    WOODCINE_URL,
    WOODCINE_SESSION_FILE,
    default_proxy,
    ensure_logged_page,
    load_session,
)

WOODCINE_HOST = WOODCINE_URL.replace("https://", "")


class WoodcineApiError(PanelApiError):
    def __init__(self, path: str, status: int, body: str):
        super().__init__(path, status, body, vendor="Woodcine")


class WoodcineApiClient(PanelApiClient):
    """GET-only na API do Woodcine com token de woodcine_session.json.

    `transport=None` usa requests (motor de teste; CF bloqueia em produção).
    Produção: use `open_client()`, que injeta o transporte do browser.
    """

    FAST_SYNC = True  # validado ×4: sync HTTP vs browser, contagens idênticas (03/10/2026)

    API_BASE = WOODCINE_API
    HOST = WOODCINE_HOST
    VENDOR = "woodcine"
    API_ERROR = WoodcineApiError
    DEFAULT_SESSION_FILE = WOODCINE_SESSION_FILE
    _AUTH = sys.modules[__name__]


@contextmanager
def open_client(session_path: str = WOODCINE_SESSION_FILE, proxy: str = None, guard=None, transport: str = None):
    """
    Cliente com transporte do browser (o único que o Cloudflare aceita).

    Abre o browser com a sessão salva (reutiliza se válida, senão refaz
    login) e devolve o client. session_path: default WOODCINE_SESSION_FILE,
    ancorado em __file__ (A1: default relativo quebrava cron/CWD≠raiz).
    """
    with open_client_for(WoodcineApiClient, session_path, proxy, guard, transport) as c:
        yield c
