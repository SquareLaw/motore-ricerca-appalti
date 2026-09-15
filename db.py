"""
db.py - Shared schema setup. Both ingest scripts import create_schema() from here.

Uses pg8000 instead of psycopg2. pg8000 is a pure-Python Postgres driver -
no compiled C extension / DLL - which avoids Windows "Application Control"
policies that block native binaries on locked-down/corporate machines.

One table, two content types ('norma' and 'giurisprudenza'), so a single
hybrid search query can pull relevant results from both at once.
"""

import os
from urllib.parse import urlparse
from pg8000.native import Connection

DATABASE_URL = os.environ["DATABASE_URL"]


def get_conn() -> Connection:
    parsed = urlparse(DATABASE_URL)
    return Connection(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
        ssl_context=True,  # Render's managed Postgres requires SSL
    )


def create_schema():
    conn = get_conn()
    try:
        conn.run("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.run("""
            CREATE TABLE IF NOT EXISTS documenti (
                id TEXT PRIMARY KEY,
                tipo TEXT NOT NULL,
                riferimento TEXT,
                testo TEXT,
                fonte_url TEXT,
                embedding VECTOR(1024),
                search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('italian', coalesce(testo, ''))) STORED
            );
        """)
        conn.run("CREATE INDEX IF NOT EXISTS idx_search ON documenti USING GIN(search_vector);")
        conn.run("CREATE INDEX IF NOT EXISTS idx_tipo ON documenti (tipo);")
    finally:
        conn.close()


def embedding_to_sql(embedding: list[float]) -> str:
    """pg8000 doesn't know the pgvector type natively - pass it as text and
    cast with ::vector in the SQL, using this string format."""
    return "[" + ",".join(str(x) for x in embedding) + "]"
