import { NextRequest, NextResponse } from "next/server";

import { insertFeedback } from "@/lib/db";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  let body: { question?: string; answer?: string; rating?: number };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const { question, answer, rating } = body;
  if (!question || !answer || (rating !== 1 && rating !== -1)) {
    return NextResponse.json(
      { error: "Expected { question, answer, rating: 1 | -1 }" },
      { status: 400 },
    );
  }
  try {
    await insertFeedback(question.slice(0, 1000), answer.slice(0, 8000), rating);
    return NextResponse.json({ ok: true });
  } catch (e) {
    console.error("feedback insert failed:", e);
    return NextResponse.json({ error: "Could not save feedback" }, { status: 500 });
  }
}
