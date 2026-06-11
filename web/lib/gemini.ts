/** Direct REST calls to the Gemini API — no SDK, no framework. */

import { config } from "./config";

const BASE = "https://generativelanguage.googleapis.com/v1beta";

async function geminiFetch(path: string, body: unknown): Promise<Response> {
  const resp = await fetch(`${BASE}/${path}?key=${config.geminiApiKey}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new GeminiError(resp.status, text.slice(0, 500));
  }
  return resp;
}

export class GeminiError extends Error {
  constructor(public status: number, detail: string) {
    super(`Gemini ${status}: ${detail}`);
  }
}

/** Embed a user query (task type RETRIEVAL_QUERY to match the corpus side). */
export async function embedQuery(text: string): Promise<number[]> {
  const resp = await geminiFetch(`models/${config.embedModel}:embedContent`, {
    content: { parts: [{ text }] },
    taskType: "RETRIEVAL_QUERY",
    outputDimensionality: config.embedDim,
  });
  const json = await resp.json();
  const values = json.embedding.values as number[];
  // MRL-truncated embeddings are not unit vectors — re-normalize.
  const norm = Math.sqrt(values.reduce((s, v) => s + v * v, 0)) || 1;
  return values.map((v) => v / norm);
}

export interface GenerateOptions {
  system: string;
  user: string;
  temperature?: number;
  jsonOutput?: boolean;
}

/** Single-shot generation (used by the reranker and non-streaming callers). */
export async function generate(opts: GenerateOptions): Promise<string> {
  const resp = await geminiFetch(`models/${config.chatModel}:generateContent`, {
    systemInstruction: { parts: [{ text: opts.system }] },
    contents: [{ role: "user", parts: [{ text: opts.user }] }],
    generationConfig: {
      temperature: opts.temperature ?? 0.2,
      ...(opts.jsonOutput ? { responseMimeType: "application/json" } : {}),
    },
  });
  const json = await resp.json();
  return json.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text ?? "").join("") ?? "";
}

/** Streaming generation; yields text deltas as they arrive (SSE). */
export async function* generateStream(opts: GenerateOptions): AsyncGenerator<string> {
  const resp = await fetch(
    `${BASE}/models/${config.chatModel}:streamGenerateContent?alt=sse&key=${config.geminiApiKey}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: opts.system }] },
        contents: [{ role: "user", parts: [{ text: opts.user }] }],
        generationConfig: { temperature: opts.temperature ?? 0.2 },
      }),
    },
  );
  if (!resp.ok || !resp.body) {
    const text = await resp.text();
    throw new GeminiError(resp.status, text.slice(0, 500));
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (!payload || payload === "[DONE]") continue;
      try {
        const json = JSON.parse(payload);
        const text = json.candidates?.[0]?.content?.parts
          ?.map((p: { text?: string }) => p.text ?? "")
          .join("");
        if (text) yield text;
      } catch {
        // partial frame — ignored; complete frames carry the text
      }
    }
  }
}
