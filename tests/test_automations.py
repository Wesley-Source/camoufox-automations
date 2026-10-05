from importlib.util import find_spec

from core.automations import AUTOMATIONS


def test_inventario_consistente():
    ids = [a["id"] for a in AUTOMATIONS]
    assert len(ids) == len(set(ids)), "ids duplicados no inventário"
    for a in AUTOMATIONS:
        assert a["status"] in ("ok", "planned", "blocked"), a["id"]
        assert a["what"] and a["run"], a["id"]


def test_runs_de_automacoes_ok_existem():  # CR-28
    """Automations 'ok' apontam pra CLI real ou script existente no disco.

    Entradas de um site cujos módulos não estão instalados (repo privado
    camoufox-panels ausente) são puladas — o público valida o framework;
    com os sites juntados (join.sh), tudo é validado.
    """
    from pathlib import Path

    from interfaces.cli import cli_app

    cli_cmds = {c.name for c in cli_app.registered_commands}
    for a in AUTOMATIONS:
        if a["status"] != "ok":
            continue
        if find_spec(f"interfaces.cli.{a['site']}") is None:
            continue
        run = a["run"]
        if run.startswith("main.py "):
            cmd = run.split()[1]
            assert cmd in cli_cmds, f"{a['id']}: comando '{cmd}' não existe na CLI"
        elif run.startswith("venv/bin/python "):
            script = Path(run.split()[1])
            assert script.exists(), f"{a['id']}: script {script} não existe"


def test_destrutivo_documenta_gate_env():  # M6: run do delete trava sem o env
    from core.automations import AUTOMATIONS
    ent = next(a for a in AUTOMATIONS if a["id"] == "sigma.customer.delete")
    assert "SIGMA_ALLOW_DESTRUCTIVE=1" in ent["run"]
