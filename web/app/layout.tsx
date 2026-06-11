import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import "./globals.css";
import { REPO_URL } from "@/lib/site";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Batas — Philippine Labor Code Q&A",
  description:
    "Ask questions about the Philippine Labor Code and get answers grounded in the exact articles, with verbatim citations. Educational demo — not legal advice.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-dvh flex flex-col bg-background text-foreground font-sans">
        <header className="border-b border-edge">
          <div className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 py-3">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="text-lg font-semibold tracking-tight">Batas</span>
              <span className="hidden text-xs text-muted sm:inline">
                Philippine Labor Code Q&amp;A
              </span>
            </Link>
            <nav className="flex items-center gap-4 text-sm text-muted">
              <Link href="/how-it-works" className="hover:text-foreground">
                How it works
              </Link>
              <a
                href={REPO_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                GitHub
              </a>
            </nav>
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4">
          {children}
        </main>
        <footer className="border-t border-edge">
          <p className="mx-auto w-full max-w-3xl px-4 py-3 text-xs text-muted">
            Educational demo — <strong>not legal advice</strong>. Answers come from the text of
            PD 442 (as amended &amp; renumbered, DOLE 2022 edition) and may omit later
            amendments, special laws, or jurisprudence.
          </p>
        </footer>
      </body>
    </html>
  );
}
