/** Thin PostgREST client for the Supabase project — plain fetch, no SDK.
 *  Uses the service-role key; this module must only be imported server-side. */

import { config } from "./config";

// Supabase serves PostgREST under /rest/v1; a bare local PostgREST serves at
// the root. Override with SUPABASE_REST_PREFIX="" for local dev.
const REST_PREFIX = process.env.SUPABASE_REST_PREFIX ?? "/rest/v1";

function restUrl(path: string): string {
  return `${config.supabaseUrl}${REST_PREFIX}${path}`;
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return {
    apikey: config.supabaseServiceKey,
    Authorization: `Bearer ${config.supabaseServiceKey}`,
    "Content-Type": "application/json",
    ...extra,
  };
}

export interface RetrievedChunk {
  chunk_id: number;
  article_id: number;
  article_no: string;
  heading: string;
  book: string;
  title: string;
  content: string;
  similarity: number | null;
  rrf_score: number;
}

export async function hybridSearch(
  queryText: string,
  queryEmbedding: number[],
  matchCount: number,
): Promise<RetrievedChunk[]> {
  const resp = await fetch(restUrl("/rpc/hybrid_search"), {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({
      query_text: queryText,
      query_embedding: `[${queryEmbedding.join(",")}]`,
      match_count: matchCount,
    }),
  });
  if (!resp.ok) throw new Error(`hybrid_search failed: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

/** Number of questions this ip_hash asked in the past hour. */
export async function recentQueryCount(ipHash: string): Promise<number> {
  const since = new Date(Date.now() - 60 * 60 * 1000).toISOString();
  const url =
    restUrl("/query_log") +
    `?ip_hash=eq.${encodeURIComponent(ipHash)}&created_at=gte.${encodeURIComponent(since)}&select=id`;
  const resp = await fetch(url, {
    method: "HEAD",
    headers: headers({ Prefer: "count=exact" }),
  });
  if (!resp.ok) throw new Error(`query_log count failed: ${resp.status}`);
  const range = resp.headers.get("content-range") ?? "/0";
  return Number(range.split("/")[1] ?? 0);
}

export async function logQuery(ipHash: string, question: string): Promise<void> {
  const resp = await fetch(restUrl("/query_log"), {
    method: "POST",
    headers: headers({ Prefer: "return=minimal" }),
    body: JSON.stringify({ ip_hash: ipHash, question }),
  });
  if (!resp.ok) throw new Error(`query_log insert failed: ${resp.status}`);
}

export async function insertFeedback(
  question: string,
  answer: string,
  rating: 1 | -1,
): Promise<void> {
  const resp = await fetch(restUrl("/feedback"), {
    method: "POST",
    headers: headers({ Prefer: "return=minimal" }),
    body: JSON.stringify({ question, answer, rating }),
  });
  if (!resp.ok) throw new Error(`feedback insert failed: ${resp.status}`);
}
