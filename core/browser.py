import os

from camoufox.sync_api import Camoufox
from contextlib import contextmanager

# DNS local da máquina falha p/ alguns domínios (ex.: *.sigma.st) — forçar Google DoH.
# ponytail: TRR mode 3 = só DoH, sem fallback ao DNS do sistema quebrado.
_GOOGLE_DOH_PREFS = {
    "network.trr.mode": 3,
    "network.trr.uri": "https://dns.google/dns-query",
    "network.trr.bootstrapAddress": "8.8.8.8",
}


def is_cf_challenge(page) -> bool:
    """True se a página é challenge do Cloudflare (CF = esperar, não 'form não encontrado')."""
    try:
        title = (page.title() or "").lower()
        if "just a moment" in title or "attention required" in title:
            return True
        return page.locator(
            "#challenge-form, #cf-challenge-running, .cf-browser-verification"
        ).count() > 0
    except Exception:
        return False



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

        Guideline Hermes: fallback do proxy na camada que ABRE o browser —
        com None o browser sai pelo egress local e o CF bloqueia.
        """
        proxy = proxy or os.environ.get("SIGMA_PROXY")
        with Camoufox(headless="virtual", proxy=_normalize_proxy(proxy),
                      firefox_user_prefs=_GOOGLE_DOH_PREFS) as browser:
            page = browser.new_page()
            try:
                yield page
            finally:
                try:
                    page.close()
                except Exception:
                    pass  # browser já morto: não mascara o erro real do corpo
