import sqlite3
import json
from datetime import datetime

DB_PATH = "automation_data.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        # Salva Raw
        conn.execute(
            "INSERT INTO raw_snapshots (url, raw_json, scraped_at) VALUES (?, ?, ?)",
            (url, json.dumps(raw_data), datetime.now())
        )
        # UPSERT Limpo (Só atualiza se mudou)
        conn.execute("""
            INSERT INTO products (external_id, title, price, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(external_id) DO UPDATE SET
                title=excluded.title,
                price=excluded.price,
                updated_at=excluded.updated_at
        """, (external_id, title, price, datetime.now()))


def save_raw(url: str, raw_data):
    """Snapshot bruto (raw layer) — usado pelos scrapers de painel."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO raw_snapshots (url, raw_json, scraped_at) VALUES (?, ?, ?)",
            (url, json.dumps(raw_data, ensure_ascii=False, default=str), datetime.now()),
        )


def save_entity(kind: str, external_id: str, payload: dict | list):
    """UPSERT de entidade de painel (camada limpa genérica)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO panel_entities (kind, external_id, payload, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(kind, external_id) DO UPDATE SET
                payload=excluded.payload,
                updated_at=excluded.updated_at
        """, (kind, str(external_id),
              json.dumps(payload, ensure_ascii=False, default=str), datetime.now()))


def count_entities(kind: str = None) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        if kind:
            row = conn.execute(
                "SELECT COUNT(*) FROM panel_entities WHERE kind = ?", (kind,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM panel_entities").fetchone()
        return row[0]
