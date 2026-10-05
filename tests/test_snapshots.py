"""Testes do core.snapshots — DB de fixture em tmp_path; auditoria de escrita."""
import pytest

from core import database
from core.snapshots import (
    diff_files,
    diff_snapshots,
    load_snapshot,
    render_diff,
    take_and_save,
    take_snapshot,
)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "fixture.db")
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    return path


def test_snapshot_captura_hashes(db):
    database.save_entities("blackbr.customer", [("1", {"username": "alice"})])
    snap = take_snapshot(db_path=db)
    assert set(snap["kinds"]) == {"blackbr.customer"}
    assert "1" in snap["kinds"]["blackbr.customer"]
    assert len(snap["kinds"]["blackbr.customer"]["1"]) == 16  # sha256[:16]


def test_snapshot_igual_para_payload_ordem_diferente(db):
    database.save_entities("k", [("1", {"a": 1, "b": 2})])
    h1 = take_snapshot(db_path=db)["kinds"]["k"]["1"]
    database.save_entities("k", [("1", {"b": 2, "a": 1})])  # ordem trocada
    h2 = take_snapshot(db_path=db)["kinds"]["k"]["1"]
    assert h1 == h2  # hash canonizado: ordem de chave não é "mudança"


def test_diff_added_removed_changed(db):
    database.save_entities("k", [("1", {"v": 1}), ("2", {"v": 1})])
    antes = take_snapshot(db_path=db)
    database.save_entities("k", [("2", {"v": 2})])   # mudou
    database.save_entities("k", [("3", {"v": 9})])   # adicionou
    with database._conn() as c:                       # removeu
        c.execute("DELETE FROM panel_entities WHERE kind='k' AND external_id='1'")
    depois = take_snapshot(db_path=db)
    diff = diff_snapshots(antes, depois)
    assert diff["added"] == {"k": ["3"]}
    assert diff["removed"] == {"k": ["1"]}
    assert diff["changed"] == {"k": ["2"]}
    assert diff["changed_kinds"] == ["k"]


def test_take_and_save_arquivo_roundtrip(db, tmp_path):
    database.save_entities("k", [("1", {"a": 1})])
    antes, p_antes = take_and_save(label="before", db_path=db,
                                   out_path=str(tmp_path / "a.json"))
    database.save_entities("k", [("1", {"a": 2})])
    depois, p_depois = take_and_save(label="after", db_path=db,
                                     out_path=str(tmp_path / "b.json"))
    snap = load_snapshot(p_antes)
    assert snap["label"] == "before"
    diff = diff_files(p_antes, p_depois)
    assert diff["changed"] == {"k": ["1"]}


def test_render_diff_tabela_legivel(db):
    antes = {"kinds": {"k": {"1": "a", "2": "b"}}}
    depois = {"kinds": {"k": {"2": "c", "3": "d"}}}
    txt = render_diff(diff_snapshots(antes, depois))
    assert "kind" in txt and "added" in txt
    assert "k" in txt and "+ 3" in txt and "- 1" in txt and "~ 2" in txt


def test_render_diff_sem_mudanca_vazio(db):
    snap = take_snapshot(db_path=db)
    assert render_diff(diff_snapshots(snap, snap)) == ""


def test_site_filter_somente_prefixo(db):
    database.save_entities("blackbr.customer", [("1", {"u": "x"})])
    database.save_entities("woodcine.customer", [("2", {"u": "y"})])
    snap = take_snapshot(site="blackbr", db_path=db)
    assert set(snap["kinds"]) == {"blackbr.customer"}


def test_snapshot_arquivo_ausente_erro(db, tmp_path):
    with pytest.raises(OSError, match="não encontrado"):
        load_snapshot(str(tmp_path / "nada.json"))


def test_nao_e_snapshot_erro(db, tmp_path):
    falso = tmp_path / "falso.json"
    falso.write_text('{"foo": 1}')
    with pytest.raises(ValueError, match="snapshot válido"):
        load_snapshot(str(falso))
