import os
import sys

from camoufox.sync_api import Camoufox
from contextlib import contextmanager

# Modos de display (env HUB_DISPLAY; padrão por SO):
#   virtual — Xvfb (Linux-only): padrão em Linux, melhor evasão de anti-bot.
#   headless — headless nativo (Windows/qualquer SO; CF pode reagir diferente).
#   x11 — usa o DISPLAY externo já configurado (ex.: VcXsrv no Windows).
_HEADLESS_BY_MODE = {"virtual": "virtual", "headless": True, "x11": False}


def _display_mode() -> str:
    mode = (os.environ.get("HUB_DISPLAY") or "").strip().lower()
    if mode in _HEADLESS_BY_MODE:
        return mode
    if sys.platform == "win32":
        raise RuntimeError(
            "Display virtual (Xvfb) só existe no Linux. No Windows, escolha:\n"
            "  1) HUB_DISPLAY=headless  — browser nativo sem janela (revalide o CF painel a painel)\n"
            "  2) HUB_DISPLAY=x11       — X server externo (ex.: VcXsrv) com DISPLAY setado\n"
            "  3) Recomendado: rode o hub dentro do WSL2 (Xvfb incluso) —\n"
            "     ver README, seção 'Windows & displays'.\n"
            "Sem browser, o FAST_SYNC (sync/status via HTTP) e a busca local continuam funcionando."
        )
    return "virtual"

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
        Modo de display por env HUB_DISPLAY (virtual|headless|x11; padrão: virtual).

        Guideline Hermes: fallback do proxy na camada que ABRE o browser —
        com None o browser sai pelo egress local e o CF bloqueia.
        """
        proxy = proxy or os.environ.get("SIGMA_PROXY")
        with Camoufox(headless=_HEADLESS_BY_MODE[_display_mode()],
                      proxy=_normalize_proxy(proxy),
                      firefox_user_prefs=_GOOGLE_DOH_PREFS) as browser:
            page = browser.new_page()
            try:
                yield page
            finally:
                try:
                    page.close()
                except Exception:
                    pass  # browser já morto: não mascara o erro real do corpo
