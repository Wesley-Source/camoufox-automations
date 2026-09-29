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
