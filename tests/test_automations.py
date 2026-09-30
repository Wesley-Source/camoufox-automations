from core.automations import AUTOMATIONS


def test_inventario_consistente():
    ids = [a["id"] for a in AUTOMATIONS]
    assert len(ids) == len(set(ids)), "ids duplicados no inventário"
    for a in AUTOMATIONS:
        assert a["status"] in ("ok", "planned", "blocked"), a["id"]
        assert a["what"] and a["run"], a["id"]
