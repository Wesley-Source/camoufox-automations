"""
Snapshot do banco local + diff legível — auditoria de escrita de 1ª classe.

O padrão snapshot → write → snapshot + diff vivia disperso nos
exploradores; aqui vira ferramenta genérica (qualquer painel/kind):

    main.py snapshot before --out out/antes.json
    ... operação de escrita ...
    main.py snapshot after out/antes.json

Formato do arquivo: JSON {taken_at, db, label, kinds: {kind: {id: hash}}}
— hash sha256[:16] do payload canonizado (sort_keys). É IMPRÓPRIO para
backup (não guarda payload), mas perfeito para detectar divergência:
added/removed/changed por kind, com amostra de ids.

Segurança: snapshot é LEITURA pura; arquivo vai para out/ (gitignored).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core import database

OUT_DIR = Path(database.DB_PATH).parent / "out"


@contextmanager
def _connect(db_path: str | None):
    conn = sqlite3.connect(db_path or database.DB_PATH, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def _payload_hash(payload_text: str | None) -> str:
    try:
        canon = json.dumps(json.loads(payload_text or "null"),
                           sort_keys=True, ensure_ascii=False, default=str)
    except (ValueError, TypeError):
        canon = str(payload_text)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def take_snapshot(site: str | None = None, kind: str | None = None,
                  db_path: str | None = None) -> dict:
    """Estado atual de panel_entities: {kind: {external_id: hash}}.

    site filtra por prefixo '<site>.*'; kind é filtro exato.
    """
    where, params = [], []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if site:
        where.append("kind LIKE ? ESCAPE '\\'")
        params.append(site.replace("\\", "\\\\").replace("%", "\\%")
                      .replace("_", "\\_") + ".%")
    sql = ("SELECT kind, external_id, payload FROM panel_entities "
           + ("WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY kind, external_id")
    kinds: dict[str, dict[str, str]] = {}
    with _connect(db_path) as conn:
        for k, eid, payload in conn.execute(sql, params):
            kinds.setdefault(k, {})[eid] = _payload_hash(payload)
    return {
        "taken_at": _dt.datetime.now().isoformat(),
        "db": str(db_path or database.DB_PATH),
        "kinds": kinds,
    }


def _default_path(label: str) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUT_DIR / f"snapshot-{label}-{ts}.json"


def take_and_save(out_path: str | None = None, site: str | None = None,
                  kind: str | None = None, label: str = "before",
                  db_path: str | None = None) -> tuple[dict, str]:
    """Snapshot + persistência em JSON; devolve (snapshot, caminho)."""
    snap = take_snapshot(site=site, kind=kind, db_path=db_path)
    path = Path(out_path).expanduser() if out_path else _default_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    snap["label"] = label
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return snap, str(path)


def load_snapshot(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise OSError(f"snapshot não encontrado: {path}")
    snap = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(snap.get("kinds"), dict):
        raise ValueError(f"arquivo não é um snapshot válido: {path}")
    return snap


def diff_snapshots(before: dict, after: dict) -> dict:
    """Divergência entre dois snapshots: added/removed/changed por kind."""
    kb, ka = before["kinds"], after["kinds"]
    added: dict[str, list] = {}
    removed: dict[str, list] = {}
    changed: dict[str, list] = {}
    for kind in sorted(set(kb) | set(ka)):
        eb, ea = kb.get(kind, {}), ka.get(kind, {})
        a = sorted(set(ea) - set(eb))
        r = sorted(set(eb) - set(ea))
        c = sorted(e for e in set(ea) & set(eb) if ea[e] != eb[e])
        if a:
            added[kind] = a
        if r:
            removed[kind] = r
        if c:
            changed[kind] = c
    changed_kinds = sorted(set(added) | set(removed) | set(changed))
    return {"added": added, "removed": removed, "changed": changed,
            "changed_kinds": changed_kinds}


def diff_files(before_path: str, after_path: str) -> dict:
    return diff_snapshots(load_snapshot(before_path), load_snapshot(after_path))


def render_diff(diff: dict, max_ids: int = 8) -> str:
    """Tabela do que mudou + amostra de ids (o resto fica no JSON)."""
    if not diff["changed_kinds"]:
        return ""
    header = f"{'kind':<28}{'added':>7}{'removed':>9}{'changed':>9}"
    linhas = [header, "-" * len(header)]
    for kind in diff["changed_kinds"]:
        a, r, c = (len(diff["added"].get(kind, [])),
                   len(diff["removed"].get(kind, [])),
                   len(diff["changed"].get(kind, [])))
        linhas.append(f"{kind:<28}{a:>7}{r:>9}{c:>9}")
        for rotulo, grupo in (("+", diff["added"].get(kind, [])),
                              ("-", diff["removed"].get(kind, [])),
                              ("~", diff["changed"].get(kind, []))):
            if grupo:
                amostra = ", ".join(str(_short(i)) for i in grupo[:max_ids])
                extra = f" … (+{len(grupo) - max_ids})" if len(grupo) > max_ids else ""
                linhas.append(f"  {rotulo} {amostra}{extra}")
    return "\n".join(linhas)


def _short(eid: str, n: int = 24) -> str:
    eid = str(eid)
    return eid if len(eid) <= n else eid[:n - 1] + "…"
