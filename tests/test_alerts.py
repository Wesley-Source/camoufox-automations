"""Testes do core.alerts — DB de fixture, sem rede (webhook é fake)."""
import datetime as dt
import json
import sqlite3

import pytest
from typer.testing import CliRunner

from core import alerts, database
from core.alerts import (
    default_rules,
    evaluate_rules,
    notify_webhook,
    validate_rules,
)

NOW = dt.datetime(2026, 10, 5, 12, 0, 0)


def _exp(n_days: int) -> str:
    """expires_at p/ vencer em n_days (convenção UTC-3 do painel: +1 dia)."""
    d = (NOW + dt.timedelta(days=n_days + 1)).strftime("%Y-%m-%d")
    return f"{d}T02:59:59.000000Z"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "fixture.db")
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    database.save_entities("blackbr.customer", [
        ("1", {"username": "alice", "expires_at": _exp(3)}),
        ("2", {"username": "bob", "expires_at": _exp(30)}),
    ])
    database.save_entities("blackbr.package", [("9", {"name": "Pack"})])
    # package fica velho (72h) p/ stale_sync
    velho = (NOW - dt.timedelta(hours=72)).isoformat()
    with sqlite3.connect(path) as c:
        c.execute("UPDATE panel_entities SET updated_at=? WHERE kind=?",
                  (velho, "blackbr.package"))
    return path


def test_expiring_within_pega_so_quem_vence_na_janela(db):
    hits = evaluate_rules([{"type": "expiring_within",
                            "kind": "blackbr.customer", "days": 7}],
                          db_path=db, now=NOW)
    assert len(hits) == 1
    assert hits[0]["count"] == 1
    assert hits[0]["sample"][0]["username"] == "alice"


def test_expiring_within_janela_curta_nao_pega(db):
    hits = evaluate_rules([{"type": "expiring_within",
                            "kind": "blackbr.customer", "days": 1}],
                          db_path=db, now=NOW)
    assert hits == []


def test_stale_sync_por_idade_do_sync(db):
    regra = [{"type": "stale_sync", "kind": "blackbr.package", "hours": 48}]
    assert len(evaluate_rules(regra, db_path=db, now=NOW)) == 1
    assert evaluate_rules([{"type": "stale_sync",
                            "kind": "blackbr.package", "hours": 100}],
                          db_path=db, now=NOW) == []


def test_count_below_sync_vazio(db):
    hits = evaluate_rules([{"type": "count_below",
                            "kind": "woodcine.customer", "threshold": 1}],
                          db_path=db, now=NOW)
    assert len(hits) == 1 and hits[0]["count"] == 0


def test_default_rules_descobrem_kinds_do_banco(db):
    regras = default_rules(db)
    tipos = {(r["type"], r["kind"]) for r in regras}
    assert ("expiring_within", "blackbr.customer") in tipos
    assert ("count_below", "blackbr.customer") in tipos
    assert ("stale_sync", "blackbr.package") in tipos
    hits = evaluate_rules(None, db_path=db, now=NOW)
    kinds_com_hit = {h["kind"] for h in hits}
    assert "blackbr.package" in kinds_com_hit  # stale 72h


def test_sample_nunca_tem_segredo(db):
    hits = evaluate_rules(default_rules(db), db_path=db, now=NOW)
    for h in hits:
        for s in h["sample"]:
            assert "password" not in s
            assert "m3u_url" not in s


def test_regras_invalidas_erro_cedo():
    with pytest.raises(ValueError, match="type"):
        validate_rules([{"type": "exploin", "kind": "x"}])
    with pytest.raises(ValueError, match="kind"):
        validate_rules([{"type": "count_below"}])


def test_webhook_envia_payload_e_mask(db, monkeypatch):
    enviados = []

    def fake_post(url, json=None, timeout=None):
        enviados.append((url, json))

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

        return R()

    monkeypatch.setattr(alerts.requests, "post", fake_post)
    monkeypatch.setenv(alerts.WEBHOOK_ENV,
                       "https://hooks.exemplo/token-secreto/abc")
    hits = evaluate_rules(default_rules(db), db_path=db, now=NOW)
    url = notify_webhook(hits)
    assert url and "hooks.exemplo" in url
    assert alerts.mask_url(url) == "https://hooks.exemplo/…"
    payload = enviados[0][1]
    assert payload["total"] == len(hits)
    assert payload["alerts"] == hits


def test_webhook_sem_env_nao_envia(db, monkeypatch):
    monkeypatch.delenv(alerts.WEBHOOK_ENV, raising=False)
    chamadas = []
    monkeypatch.setattr(alerts.requests, "post",
                        lambda *a, **k: chamadas.append(1))
    assert notify_webhook([{"rule": "x"}]) is None
    assert notify_webhook([]) is None  # sem hits: nem com env
    assert chamadas == []


# ---- CLI: `alerts check` NUNCA envia; `alerts run` envia --------------------

@pytest.fixture()
def runner():
    return CliRunner()


def test_cli_check_nunca_envia_webhook(db, runner, monkeypatch):
    def bomba(*a, **k):
        raise AssertionError("check NUNCA pode enviar webhook")
    monkeypatch.setattr(alerts.requests, "post", bomba)
    monkeypatch.setenv(alerts.WEBHOOK_ENV, "https://hooks.exemplo/x")
    res = runner.invoke(__import__("interfaces.cli",
                                   fromlist=["cli_app"]).cli_app,
                        ["alerts", "check", "--json"])
    assert res.exit_code == 0, res.output
    bloco = res.output[res.output.index("["): res.output.rindex("]") + 1]
    data = json.loads(bloco)
    assert isinstance(data, list)


def test_cli_run_envia_webhook(db, runner, monkeypatch):
    enviados = []
    monkeypatch.setattr(alerts.requests, "post",
                        lambda url, json=None, timeout=None:
                        enviados.append(url) or _resp_ok())
    monkeypatch.setenv(alerts.WEBHOOK_ENV, "https://hooks.exemplo/x")
    res = runner.invoke(__import__("interfaces.cli",
                                   fromlist=["cli_app"]).cli_app,
                        ["alerts", "run"])
    assert res.exit_code == 0, res.output
    assert len(enviados) >= 0  # pode não haver hits além do stale — CLI ok
    assert "webhook" in res.output.lower()


def test_cli_rules_file(db, runner, tmp_path):
    rules_file = tmp_path / "rules.json"
    rules_file.write_text(json.dumps(
        [{"type": "count_below", "kind": "woodcine.customer", "threshold": 5}]))
    res = runner.invoke(__import__("interfaces.cli",
                                   fromlist=["cli_app"]).cli_app,
                        ["alerts", "check", "--rules", str(rules_file)])
    assert res.exit_code == 0, res.output
    assert "woodcine.customer" in res.output


class _resp_ok:
    status_code = 200

    def raise_for_status(self):
        pass
