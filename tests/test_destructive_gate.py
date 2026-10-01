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


def test_save_session_perms_0600(tmp_path):
    import os
    import stat
    from core.sigma.auth import save_session
    f = tmp_path / "s.json"
    save_session({"token": "t", "cookies": []}, str(f))
    assert stat.S_IMODE(os.stat(f).st_mode) & 0o077 == 0  # CR-12


def test_cli_login_save_usa_save_session(tmp_path, monkeypatch):  # B1
    """sigma-login --save tem que passar pela save_session (0600 atômico)."""
    import os
    import stat
    sess = {"token": "1|abc", "cookies": [{"name": "cf_clearance", "value": "x"}],
            "captured": [], "local_storage": {}}
    monkeypatch.setenv("SIGMA_USERNAME", "u")
    monkeypatch.setenv("SIGMA_PASSWORD", "p")
    monkeypatch.setattr("interfaces.cli.sigma.login", lambda u, p: sess)
    target = tmp_path / "sigma_session.json"
    monkeypatch.setattr("interfaces.cli.sigma.SESSION_FILE", str(target))
    from interfaces.cli import cli_app
    code = cli_app(["sigma-login", "--save"], standalone_mode=False)
    assert code in (None, 0)
    assert stat.S_IMODE(os.stat(target).st_mode) & 0o077 == 0
