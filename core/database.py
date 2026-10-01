import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# CR-25: ancorado na raiz do repo — cron/agentes rodando de outro cwd
# não criam um automation_data.db fantasma.
DB_PATH = str(Path(__file__).resolve().parents[1] / "automation_data.db")


@contextmanager
def _conn():
    """Conexão que COMMITA e FECHA de verdade (CR-07: `with connect()` só
    commita a transação, vaza conexão; contextlib.closing não commitaria)
    + WAL e busy_timeout (CR-26)."""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    # CR-08: sqlite3 deprecou datetime direto (py3.12+) — string ISO.
    return datetime.now().isoformat()


def init_db():
    with _conn() as conn:
        # 1. Tabela Bruta (Raw Data Lake)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                raw_json TEXT,
                scraped_at TIMESTAMP
            )
        """)
        # 2. Tabela Limpa (Cópia/Réplica dos Dados)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                external_id TEXT PRIMARY KEY,
                title TEXT,
                price REAL,
                updated_at TIMESTAMP
            )
        """)
        # 3. Entidades de painéis (Sigma etc.) — cópia limpa genérica
        conn.execute("""
            CREATE TABLE IF NOT EXISTS panel_entities (
                kind TEXT NOT NULL,
                external_id TEXT NOT NULL,
                payload TEXT,
                updated_at TIMESTAMP,
                PRIMARY KEY (kind, external_id)
            )
        """)

def save_raw_and_clean(url: str, external_id: str, title: str, price: float, raw_data: dict):
    with _conn() as conn:
        # Salva Raw
        conn.execute(
            "INSERT INTO raw_snapshots (url, raw_json, scraped_at) VALUES (?, ?, ?)",
            (url, json.dumps(raw_data), _now())
        )
        # UPSERT Limpo (Só atualiza se mudou)
        conn.execute("""
            INSERT INTO products (external_id, title, price, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
                title=excluded.title,
                price=excluded.price,
                updated_at=excluded.updated_at
        """, (external_id, title, price, _now()))


def save_raw(url: str, raw_data):
    """Snapshot bruto (raw layer) — usado pelos scrapers de painel."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO raw_snapshots (url, raw_json, scraped_at) VALUES (?, ?, ?)",
            (url, json.dumps(raw_data, ensure_ascii=False, default=str), _now()),
        )


def save_entity(kind: str, external_id: str, payload: dict | list):
    """UPSERT de entidade de painel (camada limpa genérica)."""
    save_entities(kind, [(external_id, payload)])


def save_entities(kind: str, pairs) -> int:
    """UPSERT em lote — 1 conexão/commit pro sync inteiro (antes eram
    ~700 connects por sync de clientes, cada um com fsync e janela de lock)."""
    now = _now()
    rows = [
        (kind, str(eid), json.dumps(p, ensure_ascii=False, default=str), now)
        for eid, p in pairs
    ]
    with _conn() as conn:
        conn.executemany("""
            INSERT INTO panel_entities (kind, external_id, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, external_id) DO UPDATE SET
                payload=excluded.payload,
                updated_at=excluded.updated_at
        """, rows)
    return len(rows)


def count_entities(kind: str = None) -> int:
    with _conn() as conn:
        if kind:
            row = conn.execute(
                "SELECT COUNT(*) FROM panel_entities WHERE kind = ?", (kind,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM panel_entities").fetchone()
        return row[0]


def _rows_to_entities(rows) -> list[dict]:
    return [{"id": r[0], **json.loads(r[1]), "_updated_at": r[2]} for r in rows]


def list_entities(kind: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Entidades de um kind, mais recentes primeiro (paginação simples)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT external_id, payload, updated_at FROM panel_entities "
            "WHERE kind = ? ORDER BY updated_at DESC, external_id LIMIT ? OFFSET ?",
            (kind, limit, offset),
        ).fetchall()
    return _rows_to_entities(rows)


def search_entities(kind: str, term: str, limit: int = 20) -> list[dict]:
    """Busca parcial por id ou conteúdo do payload (LIKE com escape)."""
    like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with _conn() as conn:
        rows = conn.execute(
            "SELECT external_id, payload, updated_at FROM panel_entities "
            "WHERE kind = ? AND (external_id LIKE ? ESCAPE '\\' OR payload LIKE ? ESCAPE '\\') "
            "ORDER BY updated_at DESC, external_id LIMIT ?",
            (kind, like, like, limit),
        ).fetchall()
    return _rows_to_entities(rows)
