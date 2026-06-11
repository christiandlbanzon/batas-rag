import { createHash } from "node:crypto";

import { NextRequest, NextResponse } from "next/server";

import { config, DISCLAIMER } from "@/lib/config";
import { logQuery, recentQueryCount } from "@/lib/db";
import { GeminiError, generateStream } from "@/lib/gemini";
import { buildUserPrompt, citedArticles, retrieve, SYSTEM_PROMPT } from "@/lib/rag";

export const runtime = "nodejs";
export const maxDuration = 60;

const MAX_QUESTION_CHARS = 500;

function ipHash(req: NextRequest): string {
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0].trim() ??
    req.headers.get("x-real-ip") ??
    "unknown";
  return createHash("sha256").update(ip + config.ipHashSalt).digest("hex");
}

export async function POST(req: NextRequest) {
  let body: { question?: string; stream?: boolean };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const question = body.question?.trim();
  if (!question) {
    return NextResponse.json({ error: "Missing 'question'" }, { status: 400 });
  }
  if (question.length > MAX_QUESTION_CHARS) {
    return NextResponse.json(
      { error: `Question too long (max ${MAX_QUESTION_CHARS} characters)` },
      { status: 400 },
    );
  }

  // Per-IP rate limit so one visitor can't drain the free Gemini quota.
  const hash = ipHash(req);
  try {
    const recent = await recentQueryCount(hash);
    if (recent >= config.rateLimitPerHour) {
      return NextResponse.json(
        {
          error:
            "Demo quota reached for this hour — the free tier only stretches so far. " +
            "Please come back in a bit.",
        },
        { status: 429 },
      );
    }
    await logQuery(hash, question);
  } catch (e) {
    console.error("rate limit check failed:", e);
    // Degrade open: a logging hiccup shouldn't take the demo down.
  }

  try {
    const { context, retrieved } = await retrieve(question);
    const sources = retrieved.map((c) => ({
      article_no: c.article_no,
      heading: c.heading,
      book: c.book,
      title: c.title,
      content: c.content,
      similarity: c.similarity,
      rrf_score: c.rrf_score,
      in_context: context.includes(c),
    }));
    const prompt = buildUserPrompt(question, context);

    if (body.stream === false) {
      // Blocking JSON response (curl, evals).
      let answer = "";
      for await (const delta of generateStream({ system: SYSTEM_PROMPT, user: prompt })) {
        answer += delta;
      }
      return NextResponse.json({
        answer,
        cited: citedArticles(answer),
        sources,
        disclaimer: DISCLAIMER,
      });
    }

    // SSE: sources first so the UI can render the panel while text streams.
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        const send = (event: string, data: unknown) =>
          controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        try {
          send("sources", sources);
          let answer = "";
          for await (const delta of generateStream({ system: SYSTEM_PROMPT, user: prompt })) {
            answer += delta;
            send("delta", delta);
          }
          send("done", { cited: citedArticles(answer), disclaimer: DISCLAIMER });
        } catch (e) {
          send("error", { message: friendlyError(e) });
        } finally {
          controller.close();
        }
      },
    });
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  } catch (e) {
    console.error("ask pipeline failed:", e);
    return NextResponse.json({ error: friendlyError(e) }, { status: errorStatus(e) });
  }
}

function friendlyError(e: unknown): string {
  if (e instanceof GeminiError && (e.status === 429 || e.status === 503)) {
    return "The free Gemini quota is momentarily exhausted — please try again in a minute.";
  }
  return "Something went wrong answering that — please try again.";
}

function errorStatus(e: unknown): number {
  return e instanceof GeminiError && e.status === 429 ? 429 : 500;
}
