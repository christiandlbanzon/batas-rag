"""Embed chunks with Gemini text-embedding-004 and upsert into Postgres.

- Idempotent: chunks whose content_hash already exists in the DB are skipped,
  so re-running after no corpus change performs zero embedding calls.
- Free-tier friendly: batches of 100 with a pause between batches, and
  exponential backoff on 429/5xx.
- task_type=RETRIEVAL_DOCUMENT (the query side uses RETRIEVAL_QUERY).

Connection: DATABASE_URL — either the Supabase connection-pooler URI
(Project settings -> Database) or a local pgvector Postgres for development.

Dev mode without a Gemini key: set FAKE_EMBEDDINGS=1 to write deterministic
pseudo-vectors derived from each chunk's hash. This exercises the full
chunk -> embed -> upsert -> hybrid_search path mechanically; retrieval
quality is only meaningful with real embeddings.

Usage:  python pipeline/embed.py
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

import psycopg
import requests

sys.path.insert(0, str(Path(__file__).parent))
from models import Article, Chunk

ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"

# text-embedding-004 was retired mid-2026; gemini-embedding-001 natively
# outputs 3072 dims but supports MRL truncation. We request 768 to fit the
# schema (and pgvector's HNSW 2000-dim index ceiling) and re-normalize
# client-side, as Google recommends for truncated outputs.
EMBED_MODEL = "models/gemini-embedding-001"
EMBED_DIM = 768
# Free-tier limits on gemini-embedding-001 are tight (rolling per-minute
# token budget): 100-chunk batches 429 even after backoff. 20 chunks per
# request with a pause stays comfortably inside it.
BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", 20))
BATCH_PAUSE_S = float(os.environ.get("EMBED_BATCH_PAUSE_S", 15))
MAX_RETRIES = 6
RETRY_BASE_DELAY_S = 5.0


def load_env() -> None:
    """Minimal .env loader (repo root) — no extra dependency."""
    env_file = ROOT.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def fake_embedding(content_hash: str) -> list[float]:
    """Deterministic unit vector from the chunk hash (dev mode only)."""
    raw = b""
    seed = content_hash.encode()
    while len(raw) < EMBED_DIM * 4:
        seed = hashlib.sha256(seed).digest()
        raw += seed
    values = [struct.unpack_from("<i", raw, i * 4)[0] / 2**31 for i in range(EMBED_DIM)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def gemini_embed_batch(
    texts: list[str], api_key: str, task_type: str = "RETRIEVAL_DOCUMENT"
) -> list[list[float]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/{EMBED_MODEL}:batchEmbedContents"
    payload = {
        "requests": [
            {
                "model": EMBED_MODEL,
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
                "outputDimensionality": EMBED_DIM,
            }
            for t in texts
        ]
    }
    delay = RETRY_BASE_DELAY_S
    for attempt in range(MAX_RETRIES):
        resp = requests.post(url, json=payload, params={"key": api_key}, timeout=120)
        if resp.status_code == 200:
            return [normalize_vec(e["values"]) for e in resp.json()["embeddings"]]
        if resp.status_code in (429, 500, 502, 503, 504):
            print(f"  HTTP {resp.status_code}, retrying in {delay:.0f}s "
                  f"(attempt {attempt + 1}/{MAX_RETRIES})")
            time.sleep(delay)
            delay = min(delay * 2, 120)
            continue
        raise RuntimeError(f"Gemini embed failed: {resp.status_code} {resp.text[:300]}")
    raise RuntimeError("Gemini embed: retries exhausted")


def normalize_vec(values: list[float]) -> list[float]:
    """L2-normalize: MRL-truncated embeddings are not unit vectors."""
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def to_pgvector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in values) + "]"


def upsert_articles(conn: psycopg.Connection, articles: list[Article]) -> dict[str, int]:
    """Upsert all articles; return article_no -> db id."""
    ids: dict[str, int] = {}
    with conn.cursor() as cur:
        for a in articles:
            cur.execute(
                """
                insert into articles (book, book_title, title, chapter,
                                      article_no, old_article_no, heading, body)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (article_no) do update set
                  book = excluded.book, book_title = excluded.book_title,
                  title = excluded.title, chapter = excluded.chapter,
                  old_article_no = excluded.old_article_no,
                  heading = excluded.heading, body = excluded.body
                returning id
                """,
                (a.book, a.book_title, a.title, a.chapter,
                 a.article_no, a.old_article_no, a.heading, a.body),
            )
            ids[a.article_no] = cur.fetchone()[0]
        # drop articles that disappeared from the corpus (cascades to chunks)
        cur.execute(
            "delete from articles where article_no != all(%s)",
            ([a.article_no for a in articles],),
        )
    return ids


def main() -> None:
    load_env()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit("DATABASE_URL not set (Supabase pooler URI or local Postgres)")
    fake = os.environ.get("FAKE_EMBEDDINGS") == "1"
    api_key = os.environ.get("GEMINI_API_KEY")
    if not fake and not api_key:
        sys.exit("GEMINI_API_KEY not set (or set FAKE_EMBEDDINGS=1 for dev)")

    articles = [Article(**a) for a in json.loads((OUTPUT / "articles.json").read_text(encoding="utf-8"))]
    chunks = [Chunk(**c) for c in json.loads((OUTPUT / "chunks.json").read_text(encoding="utf-8"))]

    with psycopg.connect(db_url) as conn:
        ids = upsert_articles(conn, articles)
        with conn.cursor() as cur:
            cur.execute("select article_id, chunk_index, content_hash from chunks")
            existing = {(aid, idx): h for aid, idx, h in cur.fetchall()}

        todo = [c for c in chunks
                if existing.get((ids[c.article_no], c.chunk_index)) != c.content_hash]
        print(f"{len(chunks)} chunks total; {len(chunks) - len(todo)} unchanged; "
              f"{len(todo)} to embed" + (" (FAKE)" if fake else ""))

        embedded = 0
        for i in range(0, len(todo), BATCH_SIZE):
            batch = todo[i : i + BATCH_SIZE]
            if fake:
                vectors = [fake_embedding(c.content_hash) for c in batch]
            else:
                vectors = gemini_embed_batch([c.content for c in batch], api_key)
                time.sleep(BATCH_PAUSE_S)
            with conn.cursor() as cur:
                for c, vec in zip(batch, vectors):
                    cur.execute(
                        """
                        insert into chunks (article_id, chunk_index, content, content_hash, embedding)
                        values (%s, %s, %s, %s, %s::vector)
                        on conflict (article_id, chunk_index) do update set
                          content = excluded.content,
                          content_hash = excluded.content_hash,
                          embedding = excluded.embedding
                        """,
                        (ids[c.article_no], c.chunk_index, c.content, c.content_hash,
                         to_pgvector(vec)),
                    )
            conn.commit()  # durable per batch — a crash never loses progress
            embedded += len(batch)
            print(f"  embedded {embedded}/{len(todo)}")

        # drop chunk rows beyond the current chunk count of each article
        with conn.cursor() as cur:
            keep = [(ids[c.article_no], c.chunk_index) for c in chunks]
            cur.execute(
                """
                delete from chunks where (article_id, chunk_index) not in
                  (select unnest(%s::bigint[]), unnest(%s::int[]))
                """,
                ([k[0] for k in keep], [k[1] for k in keep]),
            )
            cur.execute("select count(*), count(embedding) from chunks")
            total, with_emb = cur.fetchone()
        conn.commit()
    print(f"done: {total} chunks in DB, {with_emb} embedded, {embedded} (re)embedded this run")


if __name__ == "__main__":
    main()
