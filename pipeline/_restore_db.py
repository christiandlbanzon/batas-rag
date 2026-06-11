"""Restore articles+chunks (incl. embeddings) from the insurance dump."""
import time
from pathlib import Path

import psycopg

DB = "postgresql://postgres:test@localhost:54329/postgres"
DUMP = Path(__file__).parent / ".cache" / "db_dump.sql"

# wait for postgres to accept connections
for attempt in range(30):
    try:
        psycopg.connect(DB, connect_timeout=3).close()
        break
    except psycopg.OperationalError:
        time.sleep(2)
else:
    raise SystemExit("postgres never became ready")

schema = (Path(__file__).parent.parent / "supabase" / "schema.sql").read_text(encoding="utf-8")
local_dev = (Path(__file__).parent.parent / "supabase" / "local-dev.sql").read_text(encoding="utf-8")

text = DUMP.read_text(encoding="utf-8")
articles_part, chunks_part = text.split("-- CHUNKS\n")
articles_part = articles_part.replace("-- ARTICLES\n", "")

with psycopg.connect(DB, autocommit=True) as conn:
    conn.execute(schema)
    conn.execute(local_dev)
    conn.execute("truncate articles restart identity cascade")
    with conn.cursor().copy("copy articles from stdin") as cp:
        cp.write(articles_part)
    with conn.cursor().copy("copy chunks from stdin") as cp:
        cp.write(chunks_part)
    conn.execute("select setval(pg_get_serial_sequence('articles','id'), (select max(id) from articles))")
    conn.execute("select setval(pg_get_serial_sequence('chunks','id'), (select max(id) from chunks))")
    arts = conn.execute("select count(*) from articles").fetchone()[0]
    total, embedded = conn.execute("select count(*), count(embedding) from chunks").fetchone()
print(f"restored: {arts} articles, {total} chunks ({embedded} embedded)")
