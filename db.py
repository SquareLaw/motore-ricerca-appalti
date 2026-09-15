"""
db.py - Shared schema setup. Both ingest scripts import create_schema() from here.

One table, two content types ('norma' and 'giurisprudenza'), so a single
hybrid search query can pull relevant results from both at once.
"""

import os
import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def create_schema():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documenti (
                id TEXT PRIMARY KEY,
                tipo TEXT NOT NULL,              -- 'norma' or 'giurisprudenza'
                riferimento TEXT,                -- e.g. "Art. 35 D.Lgs. 36/2023" or "TAR Torino n. 1455/2026"
                testo TEXT,
                fonte_url TEXT,                  -- link to the primary source
                embedding VECTOR(1024),
                search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('italian', coalesce(testo, ''))) STORED
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_search ON documenti USING GIN(search_vector);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tipo ON documenti (tipo);")
        conn.commit()
