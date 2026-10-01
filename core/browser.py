from camoufox.sync_api import Camoufox
from contextlib import contextmanager

# DNS local da máquina falha p/ alguns domínios (ex.: *.sigma.st) — forçar Google DoH.
# ponytail: TRR mode 3 = só DoH, sem fallback ao DNS do sistema quebrado.
_GOOGLE_DOH_PREFS = {
    "network.trr.mode": 3,
    "network.trr.uri": "https://dns.google/dns-query",
    "network.trr.bootstrapAddress": "8.8.8.8",
}


def _normalize_proxy(proxy):
    """Camoufox espera dict {server: ...}; SIGMA_PROXY chega como str."""
    if proxy is None or isinstance(proxy, dict):
        return proxy
    return {"server": proxy}


class BrowserEngine:
    @staticmethod
    @contextmanager
    def get_page(proxy: str = None):
        """
        Garante o uso de headless='virtual' (Xvfb) para evasão de anti-bot.
        Garante o fechamento do navegador após o uso para evitar memory leak.
        """
        with Camoufox(headless="virtual", proxy=_normalize_proxy(proxy),
                      firefox_user_prefs=_GOOGLE_DOH_PREFS) as browser:
            page = browser.new_page()
            try:
                yield page
            finally:
                page.close()
