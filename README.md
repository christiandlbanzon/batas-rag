# Batas — Philippine Labor Code Q&A with receipts

[![evals](https://github.com/christiandlbanzon/batas-rag/actions/workflows/evals.yml/badge.svg)](https://github.com/christiandlbanzon/batas-rag/actions/workflows/evals.yml)

Ask questions about the Philippine Labor Code and get answers grounded in the exact
articles — every claim cited as `[Art. N]`, every source inspectable, and a committed
eval harness that proves retrieval accuracy with numbers instead of vibes.
Runs entirely on free tiers: **$0/month**.

<!-- TODO(owner): record a 60–90s GIF of the demo and embed it here -->
<!-- ![demo](docs/demo.gif) -->

**Live demo:** _pending first Vercel deploy — see [Deploying](#deploying)_

> Educational demo — **not legal advice**.

## Eval results

50-question golden set: 20 direct, 20 colloquial paraphrases, 10 out-of-corpus traps
that must produce refusals. Reports live in [`evals/results/`](evals/results/) — the
commit history doubles as the tuning changelog.

| Metric | Value |
| --- | --- |
| hit@1 | 0.575 |
| hit@4 | 0.825 |
| **hit@8** | **0.975** |
| MRR@8 | 0.693 |

Direct questions hit 100% @8; colloquial paraphrases 95% (the one miss: "free meals
removed" → the non-diminution rule, a genuine vocabulary gap — the gold article never
mentions meals). Two measured tuning results along the way: OR-joined lexemes in the
keyword arm took FTS-only hit@8 from **0.075 → 0.600** (AND semantics matched almost
nothing), and widening the fusion candidate pool 20 → 40 *hurt* (0.975 → 0.850 —
weak keyword matches flood the fusion), so the pool stays at 20.

## Architecture

```mermaid
flowchart LR
    subgraph offline [Python pipeline — runs once]
        PDF[DOLE PD 442 PDF<br/>2022 renumbered ed.] --> ING[ingest.py<br/>font-aware parse] --> CHK[chunk.py<br/>article-aware chunks] --> EMB[embed.py<br/>idempotent upsert]
    end
    subgraph supabase [Supabase free tier]
        DB[(Postgres<br/>pgvector + tsvector)]
    end
    subgraph serving [Vercel free tier]
        UI[Next.js chat UI] --> ASK["/api/ask"]
    end
    EMB --> DB
    ASK -- "1 embed query" --> GEM[Gemini free tier]
    ASK -- "2 hybrid_search RPC (RRF)" --> DB
    ASK -- "3 rerank + grounded answer" --> GEM
    EVAL[evals/run_evals.py<br/>50-question golden set] --> DB
    EVAL -.CI gate.-> GH[GitHub Actions]
```

## Engineering decisions

**Why the DOLE renumbered edition, parsed from PDF.** The Labor Code was renumbered
in 2015 (DOLE Department Advisory 01-2015); anything citing "Art. 287 Retirement" is
pre-renumbering. The only official text carrying both numberings is the DOLE PDF, so
the pipeline parses that instead of the cleaner-looking 1974 HTML on the Official
Gazette — and keeps the old numbers as metadata (`Art. 302 [287]`). The PDF
interleaves footnotes with body text in reading order; fonts separate them (body
9.5pt, footnotes 5.5pt, markers superscript-flagged), so extraction filters by font
before any regex runs.

**Why article-aware chunking.** Legal retrieval has a natural unit: the article. A
chunk never spans two articles, so a citation can never be half-right. Each chunk
carries a breadcrumb header (`Book Three > Title I > Art. 87 (Overtime Work)`) —
cheap context that helps both the embedding and the keyword index.

**Why hybrid search, and what the evals changed.** Statute language and colloquial
language barely overlap ("graveyard shift" vs "night shift differential") — vectors
handle that; exact terms ("service incentive leave") favor keywords. Both arms run as
one Postgres RPC fused with Reciprocal Rank Fusion. The golden set caught that
Postgres's `websearch_to_tsquery` ANDs every word, matching almost nothing for
natural-language questions: OR-joined lexemes raised FTS-only hit@8 8×. Top-k is
deduped to the best chunk per article — duplicates were crowding out distinct
articles.

**Why the eval harness is the feature.** A RAG demo without numbers is a chatbot.
The golden set gates every retrieval change in CI (one batched embedding call — free
tier safe), and answer-mode evals run through the real `/api/ask` path measuring
citation presence and trap refusals. Reports are committed, so tuning history is
auditable in git.

**Why no LangChain.** The whole retrieval path is ~40 lines of SQL and two REST
calls. Building on the APIs directly keeps every step debuggable and provable —
there's nothing a framework would abstract here except the understanding.

**How $0/month shaped the design.** Python serving was ruled out (free Python hosting
cold-starts badly) — the pipeline is Python, serving is Next.js API routes on Vercel.
The per-IP rate limiter (hashed IPs, one Postgres count query) exists so a single
visitor can't drain the Gemini free quota. Embeddings are hash-keyed and idempotent
so re-runs cost zero API calls. The reranker is a flag (`RERANK_ENABLED`) that fails
open when quota is tight. The eval harness paces answer-mode runs (25s between
questions) because an unpaced run blows the free-tier requests-per-minute cap.

## Repo layout

```
pipeline/   ingest.py → chunk.py → embed.py  (Python 3.12, pydantic)
evals/      golden_set.jsonl, run_evals.py, results/ (committed reports)
web/        Next.js app — chat UI + /api/ask + /api/feedback
supabase/   schema.sql — tables, HNSW + GIN indexes, hybrid_search RPC
```

## Local setup

Prereqs: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+, a Postgres with
pgvector (Supabase free project, or locally:
`docker run -d -e POSTGRES_PASSWORD=test -p 54329:5432 pgvector/pgvector:pg16`).

```bash
cp .env.example .env        # fill in keys (see comments in the file)
make setup                  # venv + deps
make pipeline               # ingest → chunk → embed (idempotent)
make evals                  # retrieval metrics on the golden set
cd web && npm install && npm run dev
```

Windows (PowerShell) equivalents:

```powershell
uv venv -p 3.12 .venv; uv pip install -p .venv -r pipeline/requirements.txt
.venv\Scripts\python pipeline\ingest.py
.venv\Scripts\python pipeline\chunk.py
.venv\Scripts\python pipeline\embed.py
.venv\Scripts\python evals\run_evals.py
```

No Gemini key yet? `FAKE_EMBEDDINGS=1` exercises the full pipeline mechanically with
placeholder vectors (and eval runs take `--fake`), clearly labeled in reports.

## Deploying

1. **Supabase** (free): create a project, paste `supabase/schema.sql` into the SQL
   editor. Grab the URL + service-role key (Settings → API) and the connection-pooler
   URI (Settings → Database) for `DATABASE_URL`.
2. **Google AI Studio** (free): create an API key → `GEMINI_API_KEY`.
3. Run the pipeline once (`make pipeline`) to populate the index.
4. **Vercel** (Hobby): import the repo, set root directory to `web/`, add env vars
   `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `IP_HASH_SALT`.
5. **GitHub Actions**: add `GEMINI_API_KEY` and `DATABASE_URL` as repo secrets so the
   eval gate runs on PRs.

## License

[MIT](LICENSE). The Labor Code text is a public-domain government work.
