"""
Exportação de datasets do banco SQLite local — engine genérico (CSV/JSON/XLSX).

Qualquer painel/site usa: os dados vivem em `panel_entities` (kind,
external_id, payload JSON, updated_at) e o export achata o payload em
colunas. Também exporta `products` e `raw_snapshots` (raw_json fica
inteiro numa coluna — pode ser dict OU lista, não se achata).

Segredo por padrão: a FUNÇÃO devolve metadados (caminho, contagem,
colunas) — nunca as linhas. O arquivo vai para `out/` (gitignored).
Máscara de colunas sensíveis (password, m3u_url...) é responsabilidade
do chamador via `fields=`; o CLI expõe `--fields` e nunca ecOA células.

Formato: inferido da extensão do `out_path` (.csv/.json/.xlsx); default
CSV. XLSX precisa de openpyxl (venv/bin/pip install openpyxl).
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core import database

OUT_DIR = Path(database.DB_PATH).parent / "out"

_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_META_COLS = ("kind", "external_id", "updated_at")


@contextmanager
def _connect(db_path: str | None):
    """Conexão só-SELECT que FECHA no fim (CR-07: `with` de sqlite3.Connection
    só commita, vaza conexão). WAL não abre em mode=ro com -shm velho — abre
    rw como o database.py, mas aqui NENHUMA query escreve."""
    conn = sqlite3.connect(db_path or database.DB_PATH, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def list_tables(db_path: str | None = None) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [r[0] for r in rows]


def list_kinds(db_path: str | None = None) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT kind FROM panel_entities ORDER BY kind").fetchall()
    return [r[0] for r in rows]


def _flatten_rows(rows: list[sqlite3.Row], table: str) -> tuple[list[str], list[dict]]:
    """Achata payload JSON de panel_entities em colunas (ordem 1ª aparição).

    Outras tabelas voltam como-coluna; valores dict/list viram JSON na célula.
    """
    records: list[dict] = []
    columns: list[str] = []

    def _add_col(name):
        if name not in columns:
            columns.append(name)

    for row in rows:
        rec: dict = {}
        if table == "panel_entities":
            for col in _META_COLS:
                rec[col] = row[col]
                _add_col(col)
            try:
                payload = json.loads(row["payload"] or "null")
            except (ValueError, TypeError):
                payload = {"_payload_bruto": str(row["payload"])[:200]}
            if isinstance(payload, dict):
                for k, v in payload.items():
                    rec[k] = v
                    _add_col(k)
            elif payload is not None:
                rec["payload"] = _cell(payload)
                _add_col("payload")
        else:
            for k in row.keys():
                rec[k] = _cell(row[k])
                _add_col(k)
        records.append(rec)
    return columns, records


def _cell(value):
    """Célula segura: dict/lista → JSON string; datetime → ISO; resto direto."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return value


def _resolve_out(table: str, out_path: str | None, fmt: str | None,
                 kind: str | None, out_dir: Path | None) -> tuple[Path, str]:
    ext = {"csv": ".csv", "json": ".json", "xlsx": ".xlsx"}
    if out_path:
        p = Path(out_path).expanduser()
        f = (fmt or p.suffix.lstrip(".") or "csv").lower()
        if f not in ext:
            raise ValueError(f"formato desconhecido: {f!r} (use csv|json|xlsx)")
        return p, f
    f = (fmt or "csv").lower()
    if f not in ext:
        raise ValueError(f"formato desconhecido: {f!r} (use csv|json|xlsx)")
    stem = f"export_{table}_{kind or 'all'}"
    stem += _dt.datetime.now().strftime("_%Y%m%d_%H%M%S")
    base = Path(out_dir) if out_dir else OUT_DIR
    return base / f"{stem}{ext[f]}", f


def export_table(
    table: str = "panel_entities",
    out_path: str | None = None,
    fmt: str | None = None,
    kind: str | None = None,
    site: str | None = None,
    fields: list[str] | None = None,
    limit: int | None = None,
    db_path: str | None = None,
    out_dir: Path | None = None,
) -> dict:
    """Exporta uma tabela do banco para arquivo; devolve METADADOS (não linhas).

    - table: panel_entities (default) | products | raw_snapshots — validado.
    - kind: filtra panel_entities por kind exato. site: prefixo '<site>.'
      (kind='blackbr' vira 'blackbr.%').
    - fields: subconjunto de colunas (ordem respeitada). Coluna pedida que
      não existe vira erro — errar cedo, não exportar vazio.
    - limit: cap de linhas (mais recentes primeiro em panel_entities).
    """
    if not _TABLE_RE.match(table):
        raise ValueError(f"nome de tabela inválido: {table!r}")
    known = list_tables(db_path)
    if known and table not in known:
        raise ValueError(f"tabela {table!r} não existe (tabelas: {', '.join(known)})")
    if table != "panel_entities" and (kind or site):
        raise ValueError("--kind/--site só se aplicam a panel_entities")

    where, params = [], []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if site:
        where.append("kind LIKE ? ESCAPE '\\'")
        params.append(site.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + ".%")
    order = ("ORDER BY updated_at DESC, external_id" if table == "panel_entities" else "")
    sql = f"SELECT * FROM {table} {'WHERE ' + ' AND '.join(where) if where else ''} {order}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    if table == "panel_entities":
        columns, records = _flatten_rows(rows, table)
    else:
        columns = list(rows[0].keys()) if rows else []
        records = [{k: _cell(r[k]) for k in columns} for r in rows]

    if fields:
        faltando = [f for f in fields if f not in columns]
        if faltando:
            raise ValueError(f"colunas inexistentes: {', '.join(faltando)} "
                             f"(disponíveis: {', '.join(columns)})")
        columns = list(fields)
        records = [{k: rec.get(k) for k in columns} for rec in records]

    path, formato = _resolve_out(table, out_path, fmt, kind or (f"{site}.*" if site else None), out_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    if formato == "csv":
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            w.writerows(records)
    elif formato == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, default=str, indent=2)
    else:
        _write_xlsx(path, columns, records)

    return {"path": str(path), "rows": len(records),
            "columns": columns, "format": formato}


def _write_xlsx(path: Path, columns: list[str], records: list[dict]) -> None:
    try:
        from openpyxl import Workbook
    except ImportError as e:
        raise RuntimeError(
            "openpyxl não instalado — venv/bin/pip install openpyxl "
            "(ou use --format csv|json)") from e
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("export")
    ws.append(columns)
    for rec in records:
        ws.append([_cell(rec.get(c)) for c in columns])
    wb.save(path)
