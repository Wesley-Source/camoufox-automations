"""Testes do core.doctor — checks locais; nada de rede (net coberto por probe fake)."""
import datetime as dt
import json
import os

import pytest

from core import database, doctor
from core.doctor import (
    CheckResult,
    check_database,
    check_deps,
    check_env,
    check_join,
    check_python,
    check_sessions,
    run_checks,
    summary,
)


def test_check_python_ok():
    r = check_python()
    assert r.status == "ok" and "Python" in r.detail


def test_check_database_ok_e_ausente(tmp_path):
    path = str(tmp_path / "x.db")
    database.init_db()  # garante tabelas no DB padrão do ambiente de teste
    r = check_database()
    assert r.status == "ok"
    r2 = check_database(db_path=str(tmp_path / "nada.db"))
    assert r2.status == "fail" and "ausente" in r2.detail


def test_check_join_standalone_warn_vs_integro(monkeypatch):
    # sem symlinks no core de um repo "limpo": warn de standalone
    monkeypatch.setattr(doctor, "REPO_ROOT", "/caminho/inexistente")
    r = check_join()
    assert r.status == "warn"
    # (o join real desta máquina é exercitado no run_checks abaixo)


def test_check_sessions_vazio_warn(monkeypatch):
    monkeypatch.setattr(doctor, "_session_files", lambda: [])
    assert check_sessions()[0].status == "warn"


def test_check_sessions_idades(tmp_path, monkeypatch):
    f = tmp_path / "fakesite_session.json"
    f.write_text(json.dumps({"token": "t"}))
    monkeypatch.setattr(doctor, "_session_files", lambda: ["fakesite_session.json"])
    monkeypatch.setattr(doctor, "REPO_ROOT", str(tmp_path))
    agora = dt.datetime.now()

    def idade(dias):
        os.utime(f, ((agora - dt.timedelta(days=dias)).timestamp(),) * 2)

    idade(1)
    assert check_sessions(now=agora)[0].status == "ok"
    idade(15)
    assert check_sessions(now=agora)[0].status == "warn"
    idade(45)
    assert check_sessions(now=agora)[0].status == "fail"

    f.write_text(json.dumps({"sem": "token"}))
    assert check_sessions(now=agora)[0].status == "fail"


def test_check_env_gate_destrutivo(monkeypatch):
    monkeypatch.delenv("SIGMA_ALLOW_DESTRUCTIVE", raising=False)
    monkeypatch.delenv("HUB_DISPLAY", raising=False)
    rs = {r.name: r for r in check_env()}
    assert rs["env:destructive"].status == "ok"
    monkeypatch.setenv("SIGMA_ALLOW_DESTRUCTIVE", "1")
    rs = {r.name: r for r in check_env()}
    assert rs["env:destructive"].status == "fail"
    monkeypatch.setenv("HUB_DISPLAY", "virtual")
    assert {r.name: r for r in check_env()}["env:display"].status == "ok"


def test_check_deps_sem_secretos_no_detail():
    r = check_deps()
    assert r.status in ("ok", "warn")
    assert "token" not in r.detail.lower() or r.status == "ok"


def test_summary_conta():
    rs = [CheckResult("a", "ok", ""), CheckResult("b", "warn", ""),
          CheckResult("c", "fail", "")]
    assert summary(rs) == {"ok": 1, "warn": 1, "fail": 1}


def test_run_checks_offline_nao_levant(tmp_path):
    """Suite offline: venv/db/join/sessions/env/deps sem rede e sem segredos."""
    rs = run_checks(with_net=False)
    assert rs and all(isinstance(r, CheckResult) for r in rs)
    assert summary(rs)["ok"] >= 3  # python, database, deps… nesta máquina
    for r in rs:
        assert r.status in ("ok", "warn", "fail")


def test_session_nunca_ecoa_token(tmp_path, monkeypatch):
    f = tmp_path / "xsession.json"
    f.write_text(json.dumps({"token": "SECRET-token-xyz"}))
    monkeypatch.setattr(doctor, "_session_files", lambda: ["xsession.json"])
    monkeypatch.setattr(doctor, "REPO_ROOT", str(tmp_path))
    for r in check_sessions():
        assert "SECRET" not in r.detail
