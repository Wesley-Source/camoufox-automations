"""Cliente da API do painel blackbr — config + re-exports do base.

Toda a lógica vive em core/panel_api.py (AGENTS.md G5: correção vai no
BASE, não nas cópias). Vendor flag: UPDATE_STRIP_FIELDS=True — o update
do blackbr PROÍBE username/password/password_confirmation (422; descoberta
do lifecycle 07).
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
from core.blackbr.auth import (
    BLACKBR_API,
    BLACKBR_URL,
    BLACKBR_SESSION_FILE,
    default_proxy,
    ensure_logged_page,
    load_session,
)

BLACKBR_HOST = BLACKBR_URL.replace("https://", "")


class BlackbrApiError(PanelApiError):
    def __init__(self, path: str, status: int, body: str):
        super().__init__(path, status, body, vendor="Blackbr")


class BlackbrApiClient(PanelApiClient):
    """GET-only na API do blackbr com token de blackbr_session.json.

    `transport=None` usa requests (motor de teste; CF bloqueia em produção).
    Produção: use `open_client()`, que injeta o transporte do browser.
    """

    API_BASE = BLACKBR_API
    HOST = BLACKBR_HOST
    VENDOR = "blackbr"
    API_ERROR = BlackbrApiError
    DEFAULT_SESSION_FILE = BLACKBR_SESSION_FILE
    UPDATE_STRIP_FIELDS = True
    FAST_SYNC = True  # validado ×4: sync HTTP vs browser com contagens idênticas (03/10/2026)
    _AUTH = sys.modules[__name__]


@contextmanager
def open_client(session_path: str = BLACKBR_SESSION_FILE, proxy: str = None, guard=None, transport: str = None):
    """
    Cliente com transporte do browser (o único que o Cloudflare aceita).

    Abre o browser com a sessão salva (reutiliza se válida, senão refaz
    login) e devolve o client. session_path: default BLACKBR_SESSION_FILE,
    ancorado em __file__ (A1: default relativo quebrava cron/CWD≠raiz).
    """
    with open_client_for(BlackbrApiClient, session_path, proxy, guard, transport) as c:
        yield c
