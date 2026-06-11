"""Retrieval + answer evals for Batas over the golden set.

Retrieval mode (default — cheap, CI-friendly: 1 batched embedding call):
    python evals/run_evals.py
  Requires GEMINI_API_KEY and DATABASE_URL. For each non-trap question:
  embed -> hybrid_search (the same SQL function the app calls) -> rank of the
  gold article. Reports hit@1 / hit@4 / hit@8 and MRR@8.

Full mode (adds answer-quality checks through the real serving path):
    python evals/run_evals.py --mode full --api-url http://localhost:3000
  POSTs every question to /api/ask (stream=false) and measures citation
  presence, gold-article citation, refusal correctness on the 10 trap
  questions, and false refusals on answerable ones.

Dev self-test of the harness without a Gemini key (metrics meaningless,
report clearly labeled): add --fake.

Output: evals/results/<utc-stamp>_<git-sha>.md / .json, with deltas vs the
previous committed run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent / "pipeline"))

import psycopg  # noqa: E402
import requests  # noqa: E402

from embed import fake_embedding, gemini_embed_batch, load_env, to_pgvector  # noqa: E402
from models import EvalCase  # noqa: E402

RESULTS = ROOT / "results"
K_VALUES = (1, 4, 8)
REFUSAL_PREFIX = "The Labor Code excerpts retrieved don't cover this"


def load_golden() -> list[EvalCase]:
    cases = [
        EvalCase(**json.loads(line))
        for line in (ROOT / "golden_set.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(cases) == 50, f"golden set has {len(cases)} cases, expected 50"
    return cases


def embed_questions(cases: list[EvalCase], api_key: str | None, fake: bool) -> list[list[float]]:
    if fake:
        import hashlib

        return [fake_embedding(hashlib.sha256(c.question.encode()).hexdigest()) for c in cases]
    return gemini_embed_batch([c.question for c in cases], api_key, task_type="RETRIEVAL_QUERY")


def run_retrieval(
    cases: list[EvalCase], embeddings: list[list[float]], db_url: str
) -> dict:
    """Per-case gold-article rank in the fused top-8, then hit@k / MRR."""
    per_case = []
    with psycopg.connect(db_url) as conn:
        for case, emb in zip(cases, embeddings):
            rows = conn.execute(
                "select article_no from hybrid_search(%s, %s::vector, %s)",
                (case.question, to_pgvector(emb), max(K_VALUES)),
            ).fetchall()
            returned = [r[0] for r in rows]
            rank = (
                returned.index(case.expected_article) + 1
                if case.expected_article in returned
                else None
            )
            per_case.append({
                "id": case.id,
                "kind": case.kind,
                "expected": case.expected_article,
                "returned": returned,
                "rank": rank,
            })

    scored = [c for c in per_case if c["expected"] is not None]
    metrics = {
        f"hit@{k}": round(
            sum(1 for c in scored if c["rank"] and c["rank"] <= k) / len(scored), 3
        )
        for k in K_VALUES
    }
    metrics["mrr@8"] = round(
        statistics.mean((1 / c["rank"]) if c["rank"] else 0.0 for c in scored), 3
    )
    by_kind = {}
    for kind in ("direct", "paraphrase"):
        subset = [c for c in scored if c["kind"] == kind]
        by_kind[kind] = round(
            sum(1 for c in subset if c["rank"] and c["rank"] <= 8) / len(subset), 3
        )
    return {"metrics": metrics, "hit@8_by_kind": by_kind, "per_case": per_case}


def run_answers(cases: list[EvalCase], api_url: str) -> dict:
    """Hit the real /api/ask serving path; measure citations + refusals."""
    per_case = []
    for case in cases:
        resp = requests.post(
            f"{api_url.rstrip('/')}/api/ask",
            json={"question": case.question, "stream": False},
            timeout=120,
        )
        if resp.status_code != 200:
            per_case.append({"id": case.id, "kind": case.kind, "error": resp.status_code})
            continue
        data = resp.json()
        answer, cited = data.get("answer", ""), data.get("cited", [])
        refused = REFUSAL_PREFIX.lower() in answer.lower()
        per_case.append({
            "id": case.id,
            "kind": case.kind,
            "refused": refused,
            "cited": cited,
            "gold_cited": case.expected_article in cited if case.expected_article else None,
            "answer_preview": answer[:200],
        })

    answerable = [c for c in per_case if c["kind"] != "trap" and "error" not in c]
    traps = [c for c in per_case if c["kind"] == "trap" and "error" not in c]
    errors = [c for c in per_case if "error" in c]
    metrics = {
        "citation_presence": round(
            sum(1 for c in answerable if c["cited"] and not c["refused"]) / len(answerable), 3
        ) if answerable else None,
        "gold_article_cited": round(
            sum(1 for c in answerable if c["gold_cited"]) / len(answerable), 3
        ) if answerable else None,
        "false_refusals": sum(1 for c in answerable if c["refused"]),
        "trap_refusal_rate": round(
            sum(1 for c in traps if c["refused"]) / len(traps), 3
        ) if traps else None,
        "request_errors": len(errors),
    }
    return {"metrics": metrics, "per_case": per_case}


def previous_run() -> dict | None:
    files = sorted(RESULTS.glob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=ROOT,
        ).stdout.strip() or "nogit"
    except OSError:
        return "nogit"


def fmt_delta(current: float | None, prev: float | None) -> str:
    if current is None or prev is None:
        return ""
    d = current - prev
    return f" ({'+' if d >= 0 else ''}{d:.3f})"


def write_report(result: dict, label: str, fake: bool) -> Path:
    prev = previous_run()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    name = f"{stamp}_{git_sha()}"
    RESULTS.mkdir(exist_ok=True)

    r = result["retrieval"]["metrics"]
    pr = (prev or {}).get("retrieval", {}).get("metrics", {})
    lines = [
        f"# Eval report — {name}",
        "",
        f"- Label: {label}",
        f"- Golden set: 50 questions (20 direct, 20 paraphrase, 10 trap)",
    ]
    if fake:
        lines += ["", "> **FAKE EMBEDDINGS** — harness self-test only; retrieval numbers are meaningless."]
    lines += [
        "",
        "## Retrieval (gold article in fused top-k)",
        "",
        "| Metric | Value | vs prev |",
        "| --- | --- | --- |",
        *[
            f"| {m} | {r[m]} |{fmt_delta(r[m], pr.get(m))} |"
            for m in (*(f"hit@{k}" for k in K_VALUES), "mrr@8")
        ],
        "",
        f"hit@8 by kind: direct {result['retrieval']['hit@8_by_kind']['direct']}, "
        f"paraphrase {result['retrieval']['hit@8_by_kind']['paraphrase']}",
    ]

    misses = [c for c in result["retrieval"]["per_case"] if c["expected"] and not c["rank"]]
    if misses:
        lines += ["", "### Retrieval misses", ""]
        lines += [f"- {c['id']}: expected Art. {c['expected']}, got {c['returned']}" for c in misses]

    if result.get("answers"):
        a = result["answers"]["metrics"]
        lines += [
            "",
            "## Answers (through /api/ask)",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            *[f"| {k} | {v} |" for k, v in a.items()],
        ]
        bad_traps = [
            c for c in result["answers"]["per_case"] if c["kind"] == "trap" and not c.get("refused")
        ]
        if bad_traps:
            lines += ["", "### Traps NOT refused", ""]
            lines += [f"- {c['id']}: {c.get('answer_preview', c.get('error'))}" for c in bad_traps]

    md = RESULTS / f"{name}.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RESULTS / f"{name}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return md


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["retrieval", "full"], default="retrieval")
    parser.add_argument("--api-url", default="http://localhost:3000")
    parser.add_argument("--label", default="")
    parser.add_argument("--fake", action="store_true", help="fake embeddings (harness self-test)")
    parser.add_argument("--min-hit8", type=float, default=None, help="exit 1 if hit@8 below this")
    args = parser.parse_args()

    load_env()
    import os

    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not db_url:
        sys.exit("DATABASE_URL not set")
    if not args.fake and not api_key:
        sys.exit("GEMINI_API_KEY not set (or use --fake for a harness self-test)")

    cases = load_golden()
    embeddings = embed_questions(cases, api_key, args.fake)
    result: dict = {
        "label": args.label,
        "fake": args.fake,
        "retrieval": run_retrieval(cases, embeddings, db_url),
    }
    if args.mode == "full":
        result["answers"] = run_answers(cases, args.api_url)

    md = write_report(result, args.label, args.fake)
    print(f"report: {md}")
    print(json.dumps(result["retrieval"]["metrics"], indent=2))
    if result.get("answers"):
        print(json.dumps(result["answers"]["metrics"], indent=2))

    hit8 = result["retrieval"]["metrics"]["hit@8"]
    if args.min_hit8 is not None and hit8 < args.min_hit8:
        sys.exit(f"FAIL: hit@8 {hit8} < {args.min_hit8}")


if __name__ == "__main__":
    main()
