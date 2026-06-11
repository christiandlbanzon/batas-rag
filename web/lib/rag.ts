/** The RAG query pipeline: embed → hybrid search → rerank → grounded prompt. */

import { config } from "./config";
import { hybridSearch, type RetrievedChunk } from "./db";
import { embedQuery, generate } from "./gemini";

export const REFUSAL_PREFIX = "The Labor Code excerpts retrieved don't cover this";

export const SYSTEM_PROMPT = `You are a careful assistant answering questions about the Philippine Labor Code (PD 442, as amended and renumbered).

Rules — follow every one:
1. Answer ONLY from the numbered excerpts provided. Never use outside knowledge, even if you are confident.
2. Cite the article for every claim, inline, in the form [Art. N]. Multiple articles: [Art. 87][Art. 88].
3. If the excerpts do not contain the answer, reply exactly: "${REFUSAL_PREFIX} — try rephrasing, or ask about hours of work, wages, leave, or termination." Do not guess, do not answer from general knowledge.
4. Quote exact figures (percentages, day counts, peso amounts) verbatim from the excerpts.
5. Be concise: a short direct answer first, then any relevant conditions or exceptions.
6. Plain text only — no markdown headers or bullets unless listing conditions.
7. Peso amounts in the Code are historical. If the question asks for a CURRENT or
   up-to-date rate or amount (today's minimum wage, current contribution rates),
   those are set by later wage orders and special laws outside this corpus — apply
   rule 3 and refuse rather than quoting an outdated figure.`;

export function buildContext(chunks: RetrievedChunk[]): string {
  return chunks
    .map(
      (c, i) =>
        `--- Excerpt ${i + 1} [Art. ${c.article_no} — ${c.heading}] (${c.book}${c.title ? ", " + c.title : ""}) ---\n${c.content}`,
    )
    .join("\n\n");
}

export function buildUserPrompt(question: string, chunks: RetrievedChunk[]): string {
  return `Excerpts from the Labor Code:\n\n${buildContext(chunks)}\n\nQuestion: ${question}`;
}

/** One cheap Flash call scoring each excerpt's relevance 0–10; falls back to
 *  the fused order on any failure. Toggled with RERANK_ENABLED. */
export async function rerank(
  question: string,
  chunks: RetrievedChunk[],
): Promise<RetrievedChunk[]> {
  if (!config.rerankEnabled || chunks.length <= config.contextChunks) return chunks;
  try {
    const listing = chunks
      .map((c, i) => `${i}: [Art. ${c.article_no} — ${c.heading}] ${c.content.slice(0, 400)}`)
      .join("\n\n");
    const raw = await generate({
      system:
        "Score how relevant each numbered excerpt is for answering the question, 0 (irrelevant) to 10 (directly answers). " +
        'Return ONLY a JSON array: [{"i": <index>, "score": <0-10>}, ...] covering every index.',
      user: `Question: ${question}\n\nExcerpts:\n${listing}`,
      temperature: 0,
      jsonOutput: true,
    });
    const scores = JSON.parse(raw) as { i: number; score: number }[];
    const byIndex = new Map(scores.map((s) => [s.i, s.score]));
    return chunks
      .map((c, i) => ({ c, score: byIndex.get(i) ?? 0 }))
      .sort((a, b) => b.score - a.score)
      .map((x) => x.c);
  } catch {
    return chunks; // rerank is an optimization, never a point of failure
  }
}

export interface RetrievalResult {
  /** Chunks in final rank order, capped to the context budget. */
  context: RetrievedChunk[];
  /** Everything hybrid search returned, for the sources panel. */
  retrieved: RetrievedChunk[];
}

export async function retrieve(question: string): Promise<RetrievalResult> {
  const embedding = await embedQuery(question);
  const retrieved = await hybridSearch(question, embedding, config.retrieveChunks);
  const ranked = await rerank(question, retrieved);
  return { context: ranked.slice(0, config.contextChunks), retrieved: ranked };
}

/** Articles cited as [Art. N] in the answer text. Tolerates sub-article
 *  suffixes the model sometimes adds: [Art. 94 (b)], [Art. 137(a)]. */
export function citedArticles(answer: string): string[] {
  const cited = new Set<string>();
  for (const m of answer.matchAll(/\[Art\.\s*(\d+(?:-[A-Z])?)\s*(?:\([a-z0-9]+\))?\]/gi)) {
    cited.add(m[1]);
  }
  return [...cited];
}
