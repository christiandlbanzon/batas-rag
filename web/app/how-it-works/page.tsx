import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { Metadata } from "next";

import { REPO_URL } from "@/lib/site";

export const metadata: Metadata = {
  title: "How it works — Batas",
  description:
    "Architecture and retrieval eval results for Batas, a RAG system over the Philippine Labor Code.",
};

interface EvalSummary {
  name: string;
  fake: boolean;
  label: string;
  metrics: Record<string, number>;
}

/** Latest committed eval report, read at build time. */
function latestEval(): EvalSummary | null {
  try {
    const dir = join(process.cwd(), "..", "evals", "results");
    const files = readdirSync(dir).filter((f) => f.endsWith(".json")).sort();
    const name = files[files.length - 1];
    if (!name) return null;
    const data = JSON.parse(readFileSync(join(dir, name), "utf-8"));
    return {
      name: name.replace(".json", ""),
      fake: Boolean(data.fake),
      label: data.label ?? "",
      metrics: data.retrieval?.metrics ?? {},
    };
  } catch {
    return null;
  }
}

const STEPS = [
  {
    n: "1",
    title: "Ingest (Python)",
    body: "The DOLE 2022 renumbered edition of PD 442 is parsed from PDF with font-aware extraction — 5.5pt footnotes and superscript markers are dropped before any regex runs. A state machine tracks Book → Title → Chapter and splits all 317 articles, keeping old article numbers from the renumbering annotations as metadata. Hard quality gates: contiguous numbering, no duplicates, no empty bodies.",
  },
  {
    n: "2",
    title: "Chunk + embed",
    body: "Chunks never cross article boundaries; each one carries a breadcrumb header (Book Three › Title I › Art. 87 — Overtime Work) so both the embedding and keyword index see its context. Gemini text-embedding-004 vectors are upserted to Supabase Postgres keyed by content hash — re-running the pipeline embeds nothing unless the text changed.",
  },
  {
    n: "3",
    title: "Retrieve",
    body: "One Postgres RPC does hybrid search: pgvector cosine top-20 + full-text top-20 (OR-joined lexemes — measured 8× better recall than AND semantics), fused with Reciprocal Rank Fusion, deduped to the best chunk per article. An optional single Gemini Flash call reranks the top 8.",
  },
  {
    n: "4",
    title: "Generate, grounded",
    body: "Gemini Flash answers under a strict system prompt: only from the retrieved excerpts, every claim cited as [Art. N], exact figures verbatim, and a fixed refusal sentence when the excerpts don't cover the question — no guessing.",
  },
  {
    n: "5",
    title: "Measure",
    body: "A 50-question golden set (20 direct, 20 colloquial, 10 out-of-corpus traps) gates every change: hit@k and MRR for retrieval, citation presence and trap-refusal correctness for answers. Reports are committed, so the tuning history lives in git. CI runs the retrieval evals on every PR.",
  },
];

export default function HowItWorks() {
  const evals = latestEval();
  return (
    <div className="py-10">
      <h1 className="text-2xl font-semibold tracking-tight">How it works</h1>
      <p className="mt-2 max-w-xl text-sm text-muted">
        Production-shaped RAG on a $0/month stack: Python pipeline, Supabase Postgres
        (pgvector + FTS), Gemini free tier, Vercel Hobby. No LangChain — the retrieval
        path is plain SQL and direct API calls.
      </p>

      <svg
        viewBox="0 0 640 150"
        className="mt-8 w-full"
        role="img"
        aria-label="Architecture: PDF to Python pipeline to Supabase, query path from browser through Next.js API to Supabase and Gemini"
      >
        <defs>
          <marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="var(--muted)" />
          </marker>
        </defs>
        {[
          { x: 8, y: 10, w: 120, label: "DOLE PD 442 PDF" },
          { x: 168, y: 10, w: 140, label: "Python pipeline" },
          { x: 348, y: 10, w: 150, label: "Supabase pgvector+FTS" },
          { x: 8, y: 95, w: 120, label: "Browser" },
          { x: 168, y: 95, w: 140, label: "Next.js /api/ask" },
          { x: 348, y: 95, w: 150, label: "hybrid_search RPC" },
          { x: 528, y: 50, w: 104, label: "Gemini Flash" },
        ].map((b) => (
          <g key={b.label}>
            <rect x={b.x} y={b.y} width={b.w} height="36" rx="8" fill="var(--card)" stroke="var(--edge)" />
            <text x={b.x + b.w / 2} y={b.y + 22} textAnchor="middle" fontSize="11" fill="var(--foreground)">
              {b.label}
            </text>
          </g>
        ))}
        <line x1="128" y1="28" x2="164" y2="28" stroke="var(--muted)" markerEnd="url(#arr)" />
        <line x1="308" y1="28" x2="344" y2="28" stroke="var(--muted)" markerEnd="url(#arr)" />
        <line x1="128" y1="113" x2="164" y2="113" stroke="var(--muted)" markerEnd="url(#arr)" />
        <line x1="308" y1="113" x2="344" y2="113" stroke="var(--muted)" markerEnd="url(#arr)" />
        <line x1="423" y1="91" x2="423" y2="50" stroke="var(--muted)" markerEnd="url(#arr)" />
        <line x1="498" y1="113" x2="540" y2="90" stroke="var(--muted)" markerEnd="url(#arr)" />
      </svg>

      <ol className="mt-8 space-y-5">
        {STEPS.map((s) => (
          <li key={s.n} className="flex gap-4">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft font-mono text-sm font-semibold text-accent">
              {s.n}
            </span>
            <div>
              <h2 className="text-sm font-semibold">{s.title}</h2>
              <p className="mt-1 text-sm leading-relaxed text-muted">{s.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <h2 className="mt-10 text-lg font-semibold">Latest eval numbers</h2>
      {evals ? (
        <div className="mt-3">
          {evals.fake && (
            <p className="mb-2 rounded-lg border border-edge bg-card px-3 py-2 text-xs text-muted">
              Harness self-test with placeholder vectors — real-embedding baseline lands with
              the first production index.
            </p>
          )}
          <table className="w-full max-w-sm text-sm">
            <tbody>
              {Object.entries(evals.metrics).map(([k, v]) => (
                <tr key={k} className="border-b border-edge">
                  <td className="py-1.5 font-mono text-xs text-muted">{k}</td>
                  <td className="py-1.5 text-right font-mono">{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">
            Run {evals.name}
            {evals.label ? ` — ${evals.label}` : ""}. Full history in{" "}
            <a className="underline hover:text-foreground" href={`${REPO_URL}/tree/main/evals/results`}>
              evals/results
            </a>
            .
          </p>
        </div>
      ) : (
        <p className="mt-3 text-sm text-muted">
          No eval reports found at build time — see{" "}
          <a className="underline hover:text-foreground" href={REPO_URL}>
            the repo
          </a>
          .
        </p>
      )}
    </div>
  );
}
