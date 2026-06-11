/** Server-side configuration. All secrets stay on the server — nothing here
 *  is ever exposed via NEXT_PUBLIC_*. */

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
}

export const config = {
  get geminiApiKey() {
    return required("GEMINI_API_KEY");
  },
  get supabaseUrl() {
    return required("SUPABASE_URL").replace(/\/$/, "");
  },
  get supabaseServiceKey() {
    return required("SUPABASE_SERVICE_ROLE_KEY");
  },
  get ipHashSalt() {
    return process.env.IP_HASH_SALT ?? "batas-default-salt";
  },
  get rateLimitPerHour() {
    return Number(process.env.RATE_LIMIT_PER_HOUR ?? 20);
  },
  get rerankEnabled() {
    return (process.env.RERANK_ENABLED ?? "true") !== "false";
  },
  chatModel: process.env.GEMINI_CHAT_MODEL ?? "gemini-2.5-flash",
  embedModel: "text-embedding-004",
  /** Chunks fed to the generator after fusion/rerank (context cap). */
  contextChunks: 5,
  /** Chunks returned from hybrid search before reranking. */
  retrieveChunks: 8,
};

export const DISCLAIMER =
  "Educational demo — not legal advice. Answers are generated from the text of " +
  "the Labor Code (PD 442, as amended and renumbered, DOLE 2022 edition) and may " +
  "omit later amendments, special laws, or jurisprudence.";
