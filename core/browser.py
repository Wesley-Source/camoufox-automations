from camoufox.sync_api import Camoufox
from contextlib import contextmanager

class BrowserEngine:
    @staticmethod
    @contextmanager
    def get_page(proxy: str = None):
        """
        Garante o uso de headless='virtual' (Xvfb) para evasão de anti-bot.
        Garante o fechamento do navegador após o uso para evitar memory leak.
        """
        with Camoufox(headless="virtual", proxy=proxy) as browser:
            page = browser.new_page()
            try:
                yield page
            finally:
                page.close()
