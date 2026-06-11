"""CI gate: retrieval quality on the golden set must stay above threshold.

Skips when GEMINI_API_KEY / DATABASE_URL are unavailable (e.g. fork PRs
without repo secrets) rather than failing.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

from embed import load_env  # noqa: E402

load_env()

HIT8_THRESHOLD = 0.9

needs_secrets = pytest.mark.skipif(
    not (os.environ.get("GEMINI_API_KEY") and os.environ.get("DATABASE_URL")),
    reason="GEMINI_API_KEY / DATABASE_URL not configured",
)


def test_golden_set_shape():
    from run_evals import load_golden

    cases = load_golden()
    kinds = {k: sum(1 for c in cases if c.kind == k) for k in ("direct", "paraphrase", "trap")}
    assert kinds == {"direct": 20, "paraphrase": 20, "trap": 10}
    assert all(c.expected_article is None for c in cases if c.kind == "trap")
    assert all(c.expected_article for c in cases if c.kind != "trap")
    assert len({c.id for c in cases}) == 50


def test_golden_articles_exist_in_corpus():
    from run_evals import load_golden

    articles_path = Path(__file__).parent.parent / "pipeline" / "output" / "articles.json"
    known = {a["article_no"] for a in json.loads(articles_path.read_text(encoding="utf-8"))}
    missing = [
        c.id for c in load_golden() if c.expected_article and c.expected_article not in known
    ]
    assert not missing, f"golden cases reference unknown articles: {missing}"


@needs_secrets
def test_retrieval_hit8():
    from run_evals import embed_questions, load_golden, run_retrieval

    cases = load_golden()
    embeddings = embed_questions(cases, os.environ["GEMINI_API_KEY"], fake=False)
    result = run_retrieval(cases, embeddings, os.environ["DATABASE_URL"])
    hit8 = result["metrics"]["hit@8"]
    misses = [c["id"] for c in result["per_case"] if c["expected"] and not c["rank"]]
    assert hit8 >= HIT8_THRESHOLD, f"hit@8 {hit8} < {HIT8_THRESHOLD}; misses: {misses}"
