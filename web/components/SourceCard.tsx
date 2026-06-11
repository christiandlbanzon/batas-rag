"use client";

import { useState } from "react";

export interface Source {
  article_no: string;
  heading: string;
  book: string;
  title: string;
  content: string;
  similarity: number | null;
  rrf_score: number;
  in_context: boolean;
}

/** Strips the breadcrumb header line the pipeline prepends to each chunk —
 *  the card already shows that context. */
function chunkBody(content: string): string {
  const newline = content.indexOf("\n");
  return newline > 0 ? content.slice(newline + 1) : content;
}

export function SourceCard({ source, cited }: { source: Source; cited: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={`overflow-hidden rounded-lg border transition ${
        cited ? "border-accent/50" : "border-edge"
      } bg-card`}
    >
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span
          className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-xs font-semibold ${
            cited ? "bg-accent-soft text-accent" : "bg-edge text-muted"
          }`}
        >
          Art. {source.article_no}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm">{source.heading}</span>
        {source.similarity !== null && (
          <span className="hidden shrink-0 font-mono text-xs text-muted sm:inline">
            {(source.similarity * 100).toFixed(0)}% match
          </span>
        )}
        <span className="shrink-0 text-xs text-muted">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="border-t border-edge px-3 py-2">
          <p className="text-xs text-muted">
            {source.book}
            {source.title ? ` › ${source.title}` : ""}
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">
            {chunkBody(source.content)}
          </p>
        </div>
      )}
    </div>
  );
}
