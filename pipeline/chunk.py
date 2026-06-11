"""Chunk parsed articles into retrieval units.

Rules:
- A chunk never spans two articles (article-aware boundaries).
- Target ~400-600 tokens per chunk; most articles fit in one chunk.
- Long articles are split at sentence boundaries with ~80 tokens of overlap.
- Every chunk is prefixed with a breadcrumb header, e.g.
  "Book Three > Title I — Working Conditions and Rest Periods > Art. 87 (Overtime Work)"
  so both the embedding and the keyword index see the article's context.

Token counts are estimated as chars/4 — close enough for sizing decisions,
and avoids a tokenizer dependency for a one-time pipeline.

Usage:  python pipeline/chunk.py
Output: pipeline/output/chunks.json
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import Article, Chunk

ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"

TARGET_TOKENS = 500   # aim for chunks around this size
MAX_TOKENS = 600      # split an article only if it exceeds this
OVERLAP_TOKENS = 80   # sentence overlap between consecutive chunks


def est_tokens(text: str) -> int:
    return len(text) // 4


def split_sentences(text: str) -> list[str]:
    """Split on sentence ends and enumeration line breaks, keeping delimiters."""
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(\d])|\n", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_article(article: Article) -> list[Chunk]:
    header = article.breadcrumb
    body = article.body

    if est_tokens(header + body) <= MAX_TOKENS:
        content = f"{header}\n{body}"
        return [make_chunk(article, 0, content)]

    sentences = split_sentences(body)
    chunks: list[Chunk] = []
    window: list[str] = []

    def window_tokens() -> int:
        return est_tokens(" ".join(window))

    for sentence in sentences:
        window.append(sentence)
        if window_tokens() >= TARGET_TOKENS:
            content = f"{header}\n" + " ".join(window)
            chunks.append(make_chunk(article, len(chunks), content))
            # keep the tail as overlap for the next window
            tail: list[str] = []
            while window and est_tokens(" ".join(tail)) < OVERLAP_TOKENS:
                tail.insert(0, window.pop())
            window = tail
    if window:
        leftover = " ".join(window)
        # avoid a tiny trailing chunk that is pure overlap of the previous one
        if not chunks or est_tokens(leftover) > OVERLAP_TOKENS:
            content = f"{header}\n{leftover}"
            chunks.append(make_chunk(article, len(chunks), content))
    return chunks


def make_chunk(article: Article, index: int, content: str) -> Chunk:
    return Chunk(
        article_no=article.article_no,
        chunk_index=index,
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def main() -> None:
    articles = [
        Article(**a)
        for a in json.loads((OUTPUT / "articles.json").read_text(encoding="utf-8"))
    ]
    all_chunks: list[Chunk] = []
    for article in articles:
        all_chunks.extend(chunk_article(article))

    multi = {}
    for c in all_chunks:
        multi[c.article_no] = multi.get(c.article_no, 0) + 1
    split_articles = {k: v for k, v in multi.items() if v > 1}
    sizes = [est_tokens(c.content) for c in all_chunks]

    out = OUTPUT / "chunks.json"
    out.write_text(
        json.dumps([c.model_dump() for c in all_chunks], indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"{len(articles)} articles -> {len(all_chunks)} chunks ({len(split_articles)} articles split)")
    print(f"chunk tokens: min {min(sizes)}, median {sorted(sizes)[len(sizes)//2]}, max {max(sizes)}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
