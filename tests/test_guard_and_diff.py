"""Onda 4: install_guard fail-closed auditável, diff do snapshot 06 e gates
destrutivos no caminho FELIZ (gate aberto + flag → operação acontece)."""
import importlib
import json

from core.sigma.explore._guard import install_guard


# ---- install_guard -----------------------------------------------------------

class FakeRequest:
    def __init__(self, method, url):
        self.method = method
        self.url = url


class FakeRoute:
    def __init__(self, method, url, explode=False):
        self.request = FakeRequest(method, url)
        self.explode = explode
        self.continued = False
        self.aborted = None

    def continue_(self):
        if self.explode:
            raise RuntimeError("rota sumiu")
        self.continued = True

    def abort(self, reason):
        if self.explode:
            raise RuntimeError("rota sumiu")
        self.aborted = reason


class FakeGuardPage:
    def __init__(self):
        self.handler = None

    def route(self, pattern, handler):
        self.handler = handler


def test_guard_passa_get_e_aborta_mutante():
    page = FakeGuardPage()
    blocked = install_guard(page)
    page.handler(FakeRoute("GET", "https://x/api/customers"))
    page.handler(FakeRoute("post", "https://x/api/customers"))  # minúsculo também pega
    page.handler(FakeRoute("DELETE", "https://x/api/customers/abc"))
    assert blocked == [
        {"method": "post", "url": "https://x/api/customers"},
        {"method": "DELETE", "url": "https://x/api/customers/abc"},
    ]


def test_guard_nao_derruba_sessao_se_rota_explode():
    """Rota que desaparece no meio NÃO pode levantar — e nem liberar (o
    default do Playwright pra rota não tratada é abortar depois do timeout)."""
    page = FakeGuardPage()
    blocked = install_guard(page)
    page.handler(FakeRoute("GET", "https://x/y", explode=True))  # não levanta
    page.handler(FakeRoute("POST", "https://x/y", explode=True))
    # o POST chegou a ser REGISTRADO (append antes do abort) — e nenhuma
    # exceção escapou do handler
    assert blocked == [{"method": "POST", "url": "https://x/y"}]


# ---- diff do snapshot 06 -----------------------------------------------------

def _snap_mod():
    return importlib.import_module(
        "core.sigma.explore." + "06_customers_snapshot"
    )


def test_diff_snapshot_detecta_tudo():
    diff = _snap_mod().diff
    old = {"a": {"nome": "x", "status": "ACTIVE"}, "b": {"nome": "y"}, "c": {"nome": "z"}}
    new = {"a": {"nome": "x", "status": "SUSPENDED"}, "b": {"nome": "y"}, "d": {"nome": "w"}}
    d = diff(old, new)
    assert d["added"] == ["d"]
    assert d["removed"] == ["c"]
    assert d["changed"] == {"a": ["status"]}


def test_diff_snapshot_zero_mudancas():
    same = {"a": {"nome": "x"}}
    d = _snap_mod().diff(same, json.loads(json.dumps(same)))
    assert d == {"added": [], "removed": [], "changed": {}}


# ---- gates destrutivos: caminho feliz ----------------------------------------

class FakeClientCM:
    """open_client falso: devolve client enlatado sem abrir browser."""

    def __init__(self, client):
        self.client = client

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        return self.client

    def __exit__(self, *exc):
        return False


def test_mcp_excluir_com_gate_e_confirmar_executa(monkeypatch):
    monkeypatch.setenv("SIGMA_ALLOW_DESTRUCTIVE", "1")

    class C:
        def delete_customer(self, cid):
            self.called = cid
            return {"deleted_at": "2026-10-01"}

    c = C()
    import interfaces.mcp.sigma as m
    monkeypatch.setattr(m, "open_client", FakeClientCM(c))
    res = m._excluir_cliente_sigma("ZZZ1", True)
    assert c.called == "ZZZ1"
    assert "deletado" in res.lower() or "deleted" in res.lower() or "ZZZ1" in res


def test_cli_delete_com_gate_e_yes_executa(monkeypatch):
    monkeypatch.setenv("SIGMA_ALLOW_DESTRUCTIVE", "1")

    class C:
        def __init__(self):
            self.called = None

        def delete_customer(self, cid):
            self.called = cid
            return {"deleted_at": "2026-10-01"}

    c = C()
    import interfaces.cli as cli_pkg
    import interfaces.cli.sigma as s
    monkeypatch.setattr(s, "open_client", FakeClientCM(c))
    code = cli_pkg.cli_app(
        ["sigma-customer-delete", "ZZZ2", "--yes"], standalone_mode=False
    )
    assert code is None  # sucesso: sem exit code de erro
    assert c.called == "ZZZ2"
