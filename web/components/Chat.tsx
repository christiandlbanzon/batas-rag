"use client";

import { useRef, useState } from "react";

import { EXAMPLE_QUESTIONS } from "@/lib/site";

import { SourceCard, type Source } from "./SourceCard";

interface Exchange {
  question: string;
  answer: string;
  sources: Source[];
  cited: string[];
  done: boolean;
  error?: string;
  feedback?: 1 | -1;
}

export function Chat() {
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function ask(question: string) {
    if (!question.trim() || busy) return;
    setBusy(true);
    setInput("");
    setExchanges((xs) => [
      ...xs,
      { question, answer: "", sources: [], cited: [], done: false },
    ]);
    const patch = (p: Partial<Exchange> | ((x: Exchange) => Partial<Exchange>)) =>
      setExchanges((xs) => {
        const last = xs[xs.length - 1];
        const partial = typeof p === "function" ? p(last) : p;
        return [...xs.slice(0, -1), { ...last, ...partial }];
      });

    try {
      const resp = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        patch({ done: true, error: data.error ?? `Request failed (${resp.status})` });
        return;
      }
      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          let event = "message";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event: ")) event = line.slice(7).trim();
            if (line.startsWith("data: ")) data += line.slice(6);
          }
          if (!data) continue;
          const payload = JSON.parse(data);
          if (event === "sources") patch({ sources: payload });
          else if (event === "delta") patch((x) => ({ answer: x.answer + payload }));
          else if (event === "done") patch({ done: true, cited: payload.cited });
          else if (event === "error") patch({ done: true, error: payload.message });
        }
        bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      }
      patch({ done: true });
    } catch {
      patch({ done: true, error: "Network error — please try again." });
    } finally {
      setBusy(false);
    }
  }

  async function sendFeedback(index: number, rating: 1 | -1) {
    const x = exchanges[index];
    setExchanges((xs) =>
      xs.map((e, i) => (i === index ? { ...e, feedback: rating } : e)),
    );
    await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: x.question, answer: x.answer, rating }),
    }).catch(() => {});
  }

  return (
    <div className="flex flex-1 flex-col py-6">
      {exchanges.length === 0 && (
        <div className="my-auto text-center">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Ask the Labor Code
          </h1>
          <p className="mx-auto mt-3 max-w-md text-sm text-muted">
            Answers grounded in the exact articles of PD 442 (as amended &amp; renumbered),
            with citations you can inspect.
          </p>
          <div className="mx-auto mt-6 flex max-w-xl flex-wrap justify-center gap-2">
            {EXAMPLE_QUESTIONS.map((q) => (
              <button
                key={q}
                onClick={() => ask(q)}
                className="rounded-full border border-edge bg-card px-3 py-1.5 text-xs text-muted transition hover:border-accent hover:text-foreground"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-8">
        {exchanges.map((x, i) => (
          <div key={i}>
            <div className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-accent-soft px-4 py-2 text-sm">
                {x.question}
              </p>
            </div>
            <div className="mt-4">
              {x.error ? (
                <p className="rounded-lg border border-edge bg-card px-4 py-3 text-sm text-muted">
                  {x.error}
                </p>
              ) : (
                <>
                  <p className="whitespace-pre-wrap text-[15px] leading-relaxed">
                    {x.answer}
                    {!x.done && (
                      <span className="ml-1 inline-block h-4 w-2 animate-pulse rounded-sm bg-accent align-text-bottom" />
                    )}
                  </p>
                  {x.sources.length > 0 && (
                    <div className="mt-4">
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                        Sources
                      </p>
                      <div className="space-y-2">
                        {x.sources
                          .filter((s) => s.in_context)
                          .map((s) => (
                            <SourceCard
                              key={`${s.article_no}-${s.heading}`}
                              source={s}
                              cited={x.cited.includes(s.article_no)}
                            />
                          ))}
                      </div>
                    </div>
                  )}
                  {x.done && !x.error && x.answer && (
                    <div className="mt-3 flex items-center gap-2 text-muted">
                      <span className="text-xs">Was this helpful?</span>
                      <button
                        aria-label="Helpful"
                        disabled={x.feedback !== undefined}
                        onClick={() => sendFeedback(i, 1)}
                        className={`rounded p-1 text-sm transition hover:bg-card ${x.feedback === 1 ? "text-accent" : ""}`}
                      >
                        👍
                      </button>
                      <button
                        aria-label="Not helpful"
                        disabled={x.feedback !== undefined}
                        onClick={() => sendFeedback(i, -1)}
                        className={`rounded p-1 text-sm transition hover:bg-card ${x.feedback === -1 ? "text-accent" : ""}`}
                      >
                        👎
                      </button>
                      {x.feedback !== undefined && <span className="text-xs">Thanks!</span>}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
        className="sticky bottom-4 mt-8"
      >
        <div className="flex items-center gap-2 rounded-2xl border border-edge bg-card p-2 shadow-sm">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. How is overtime pay computed?"
            maxLength={500}
            className="flex-1 bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-xl bg-accent px-4 py-2 text-sm font-medium text-white transition disabled:opacity-40 dark:text-stone-900"
          >
            {busy ? "Thinking…" : "Ask"}
          </button>
        </div>
      </form>
    </div>
  );
}
