"""Core não pode poluir stdout (suja o JSON-RPC do MCP) — só stderr."""
import typer

import core.sigma.auth as auth
from core.sigma.auth import ensure_logged_page


class FakePage:
    """Suficiente p/ _restore_session + _session_still_valid (ramo reused)."""

    def __init__(self):
        self.url = "https://lideriptv.sigma.st/#/dashboard"

    class context:
        @staticmethod
        def add_cookies(cookies):
            pass

        @staticmethod
        def add_init_script(script):
            pass

    def add_init_script(self, script):
        pass

    def locator(self, *a, **k):
        class _L:
            def count(self):
                return 0

        return _L()

    def evaluate(self, *a, **k):
        # fetch /api/auth/me passa o token como 2º arg e espera status int;
        # evaluate de localStorage (1 arg) devolve o token.
        return 200 if len(a) > 1 else "1|ok"

    def goto(self, *a, **k):
        pass

    def on(self, *a, **k):
        pass


class FakeCtx:
    def __enter__(self):
        return FakePage()

    def __exit__(self, *a):
        return False


def test_secho_do_core_vai_para_stderr(monkeypatch, tmp_path):
    """Caminho de reuso da sessão: todo secho do core deve ter err=True."""
    calls = []
    # secho do core vive em core/panel_auth.py — patch global do typer pega
    # qualquer módulo que o importe (typer é singleton).
    monkeypatch.setattr(typer, "secho", lambda *a, **kw: calls.append(kw))
    monkeypatch.setattr(auth, "_VALIDATE_SETTLE", 0)

    sess = {"token": "1|ok", "cookies": [], "local_storage": {}}
    monkeypatch.setattr(auth, "load_session", lambda path=None: sess)
    monkeypatch.setattr(auth.BrowserEngine, "get_page", lambda proxy=None: FakeCtx())

    sess_path = str(tmp_path / "s.json")
    with ensure_logged_page(session_path=sess_path):
        pass

    assert calls, "nenhum secho emitido — teste não exercitou o caminho"
    assert all(c.get("err") for c in calls), f"secho sem err=True: {calls}"
