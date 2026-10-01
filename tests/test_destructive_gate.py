"""CR-10: gate destrutivo — 'confirmar' do LLM não é confirmação."""
import typer

from core.sigma.auth import allow_destructive


def test_gate_destrutivo_env(monkeypatch):
    monkeypatch.delenv("SIGMA_ALLOW_DESTRUCTIVE", raising=False)
    assert allow_destructive() is False
    monkeypatch.setenv("SIGMA_ALLOW_DESTRUCTIVE", "1")
    assert allow_destructive() is True
    monkeypatch.setenv("SIGMA_ALLOW_DESTRUCTIVE", "yes")  # só '1' abre
    assert allow_destructive() is False


def test_cli_delete_sem_gate_recusa(monkeypatch):
    monkeypatch.delenv("SIGMA_ALLOW_DESTRUCTIVE", raising=False)
    from interfaces.cli import cli_app
    from core.database import init_db
    init_db()
    code = cli_app(["sigma-customer-delete", "ZZZ", "--yes"], standalone_mode=False)
    assert code == 1


def test_mcp_excluir_sem_gate_recusa(monkeypatch):
    monkeypatch.delenv("SIGMA_ALLOW_DESTRUCTIVE", raising=False)
    from interfaces.mcp.sigma import _excluir_cliente_sigma
    res = _excluir_cliente_sigma("ZZZ", True)
    assert "SIGMA_ALLOW_DESTRUCTIVE" in res
