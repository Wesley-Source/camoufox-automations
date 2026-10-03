"""Cliente da API do painel Sigma — config + re-exports do base.

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
from core.sigma.auth import (
    SIGMA_API,
    SIGMA_URL,
    SESSION_FILE,
    default_proxy,
    ensure_logged_page,
    load_session,
)

SIGMA_HOST = SIGMA_URL.replace("https://", "")


class SigmaApiError(PanelApiError):
    def __init__(self, path: str, status: int, body: str):
        super().__init__(path, status, body, vendor="Sigma")


class SigmaApiClient(PanelApiClient):
    """GET-only na API do Sigma com token de sigma_session.json.

    `transport=None` usa requests (motor de teste; CF bloqueia em produção).
    Produção: use `open_client()`, que injeta o transporte do browser.
    """

    API_BASE = SIGMA_API
    HOST = SIGMA_HOST
    VENDOR = "sigma"
    API_ERROR = SigmaApiError
    DEFAULT_SESSION_FILE = SESSION_FILE
    _AUTH = sys.modules[__name__]


@contextmanager
def open_client(session_path: str = SESSION_FILE, proxy: str = None, guard=None):
    """
    Cliente com transporte do browser (o único que o Cloudflare aceita).

    Abre o browser com a sessão salva (reutiliza se válida, senão refaz
    login) e devolve o client. session_path: default SESSION_FILE, ancorado
    em __file__ (A1: default relativo quebrava cron/CWD≠raiz).
    """
    with open_client_for(SigmaApiClient, session_path, proxy, guard) as c:
        yield c
