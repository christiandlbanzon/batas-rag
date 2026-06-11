"""Ingest the Philippine Labor Code into structured articles.

Source: DOLE 2022 edition of PD 442 "as amended and renumbered" (per DOLE
Department Advisory 01-2015), mirrored by ILO NatLex. The DOLE website itself
sits behind a Cloudflare JS challenge, so the script pulls the identical PDF
from NatLex. This is the only official edition that carries the renumbering
annotations ("ART. 302. [287] ..."), which is why we parse PDF rather than the
original-1974 HTML on the Official Gazette / LawPhil.

Parsing strategy: the PDF text layer interleaves footnotes with body text in
reading order, but fonts separate them perfectly — body is 9.5pt, footnotes
are 5.5pt, and footnote markers are superscript-flagged spans. We filter by
font before any regex sees the text.

Usage:  python pipeline/ingest.py
Output: pipeline/output/articles.json, pipeline/report.md
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF
import requests

sys.path.insert(0, str(Path(__file__).parent))
from models import Article

ROOT = Path(__file__).parent
CACHE = ROOT / ".cache"
OUTPUT = ROOT / "output"

SOURCE_URL = "https://natlex.ilo.org/dyn/natlex2/natlex2/files/download/15242/PHL15242%202022.pdf"
PDF_PATH = CACHE / "labor_code_ilo_2022.pdf"

MIN_BODY_FONT = 8.5  # body is 9.5pt; footnotes are 5.5pt
SUPERSCRIPT_FLAG = 1  # fitz span flag bit for superscript (footnote markers)

# "ART. 302. [287] Repealing Clause. — body..."  (old number optional).
# Long headings wrap across lines, so the "heading — body" split happens later,
# once enough lines are joined to reach the first em-dash.
ARTICLE_START_RE = re.compile(
    r"^ART\.\s*(?P<no>\d+(?:-[A-Z])?)\.?\s*(?:\[(?P<old>\d+(?:-[A-Z])?)\]\s*)?(?P<tail>.*)$"
)
HEADING_SPLIT_RE = re.compile(r"^(?P<heading>[^–—]{0,300}?)\s*[–—]\s*(?P<rest>.*)$", re.S)
BOOK_RE = re.compile(r"^BOOK\s+(ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN)\s*[-–—]\s*(?P<bt>.+)$", re.I)
TITLE_RE = re.compile(r"^Title\s+([IVXLC]+(?:-[A-Z])?)\b\s*[-–—]?\s*(?P<tt>.*)$")
CHAPTER_RE = re.compile(r"^Chapter\s+([IVXLC]+)\b\s*[-–—]?\s*(?P<ct>.*)$", re.I)


def download(url: str = SOURCE_URL, dest: Path = PDF_PATH) -> Path:
    """Download the corpus PDF once; reuse the cached copy on re-runs."""
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"using cached {dest.name} ({dest.stat().st_size:,} bytes)")
        return dest
    CACHE.mkdir(exist_ok=True)
    print(f"downloading {url}")
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise RuntimeError("downloaded file is not a PDF — source may have moved")
    dest.write_bytes(resp.content)
    print(f"saved {dest.name} ({len(resp.content):,} bytes)")
    return dest


def extract_body_lines(pdf_path: Path) -> list[str]:
    """Extract text lines, dropping footnotes and superscript markers by font."""
    doc = fitz.open(pdf_path)
    lines: list[str] = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                parts = []
                for span in line["spans"]:
                    if span["size"] < MIN_BODY_FONT:
                        continue  # footnote text
                    if span["flags"] & SUPERSCRIPT_FLAG:
                        continue  # footnote reference marker
                    parts.append(span["text"])
                text = "".join(parts).strip()
                if text:
                    lines.append(text)
    return lines


def normalize(text: str) -> str:
    """Tidy PDF artifacts without altering wording."""
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def parse_articles(lines: list[str]) -> tuple[list[Article], list[str]]:
    """State machine over body lines: track book/title/chapter, split on ART."""
    # The table of contents repeats the book/title lines; the body proper
    # starts at the last "PRELIMINARY TITLE" line before the (unique) ART. 1.
    art1_idx = next(i for i, l in enumerate(lines) if re.match(r"^ART\.\s*1\.", l))
    start = max(
        (i for i, l in enumerate(lines[:art1_idx]) if l.upper().startswith("PRELIMINARY TITLE")),
        default=0,
    )

    book, book_title, title, chapter = "Preliminary Title", "", "", ""
    last_struct: str | None = None  # tracks a Title/Chapter line awaiting wrapped continuation
    articles: list[Article] = []
    parse_warnings: list[str] = []
    current: dict | None = None
    body_acc: list[str] = []
    pending_heading: list[str] = []  # heading lines until the first em-dash

    def flush():
        nonlocal current, body_acc, pending_heading
        if current is not None:
            if current.get("heading") is None:
                # No "heading — body" dash (e.g. Art. 310, where the bold
                # heading flows grammatically into the sentence). Keep the
                # full text as body; derive a short display heading.
                joined = normalize(" ".join(pending_heading))
                words = joined.split()
                current["heading"] = " ".join(words[:8]).rstrip(".,;")
                body_acc = [joined]
                parse_warnings.append(
                    f"Art. {current['article_no']}: no heading dash; "
                    f"derived heading from leading words"
                )
            current["body"] = format_body(body_acc)
            articles.append(Article(**current))
        current, body_acc, pending_heading = None, [], []

    def feed(text: str):
        """Route text into the pending heading or the body."""
        nonlocal pending_heading
        if current is None:
            return
        if current.get("heading") is None:
            joined = " ".join(pending_heading + [text])
            m = HEADING_SPLIT_RE.match(joined)
            if m:
                current["heading"] = m.group("heading").rstrip(". ")
                pending_heading = []
                if m.group("rest").strip():
                    body_acc.append(m.group("rest").strip())
            else:
                pending_heading.append(text)
        else:
            body_acc.append(text)

    for raw in lines[start:]:
        line = normalize(raw)
        m = ARTICLE_START_RE.match(line)
        if m:
            flush()
            current = dict(
                article_no=m.group("no"),
                old_article_no=m.group("old"),
                heading=None,
                book=book, book_title=book_title, title=title, chapter=chapter,
            )
            if m.group("tail").strip():
                feed(m.group("tail").strip())
            last_struct = None
            continue
        bm = BOOK_RE.match(line)
        if bm:
            flush()
            book = f"Book {bm.group(1).title()}"
            book_title = normalize(bm.group("bt")).title()
            title, chapter = "", ""
            last_struct = "book"
            continue
        tm = TITLE_RE.match(line)
        if tm and len(line) < 90:
            flush()
            title = f"Title {tm.group(1)}" + (f" — {tm.group('tt').strip().title()}" if tm.group("tt").strip() else "")
            chapter = ""
            last_struct = "title"
            continue
        cm = CHAPTER_RE.match(line)
        if cm and len(line) < 90:
            flush()
            chapter = f"Chapter {cm.group(1)}" + (f" — {cm.group('ct').strip().title()}" if cm.group("ct").strip() else "")
            last_struct = "chapter"
            continue
        # Wrapped continuation of a Title/Chapter heading: an all-caps short
        # line arriving before any article opens under that heading.
        if current is None and last_struct and line.isupper() and len(line) < 60:
            if last_struct == "title":
                title += " " + line.title()
            elif last_struct == "chapter":
                chapter += " " + line.title()
            else:
                book_title += " " + line.title()
            continue
        last_struct = None
        feed(line)
    flush()
    return articles, parse_warnings


def format_body(lines: list[str]) -> str:
    """Join wrapped lines; start a fresh line at enumeration markers."""
    out: list[str] = []
    for line in lines:
        if out and re.match(r"^(\([a-z0-9]{1,3}\)|\d{1,2}\.)\s", line):
            out.append("\n" + line)
        elif out:
            out.append(" " + line)
        else:
            out.append(line)
    return "".join(out).strip()


def quality_gate(articles: list[Article]) -> list[str]:
    """Hard assertions + soft warnings. Raises on hard failures."""
    warnings: list[str] = []
    assert 300 <= len(articles) <= 340, f"article count {len(articles)} outside expected range 300–340"

    dupes = [no for no, c in Counter(a.article_no for a in articles).items() if c > 1]
    assert not dupes, f"duplicate article numbers: {dupes}"

    empty = [a.article_no for a in articles if not a.body.strip()]
    assert not empty, f"empty bodies: {empty}"

    short = [a.article_no for a in articles if len(a.body) < 40]
    if short:
        warnings.append(f"unusually short bodies (<40 chars): {short}")

    no_heading = [a.article_no for a in articles if not a.heading.strip()]
    if no_heading:
        warnings.append(f"articles without headings: {no_heading}")

    nums = [int(re.match(r"\d+", a.article_no).group()) for a in articles]
    breaks = [(a, b) for a, b in zip(nums, nums[1:]) if b not in (a, a + 1)]
    if breaks:
        warnings.append(f"non-consecutive numbering at: {breaks}")
    return warnings


def write_report(articles: list[Article], warnings: list[str]) -> None:
    renumbered = [a for a in articles if a.old_article_no]
    books = Counter(a.book for a in articles)
    rng = random.Random(42)
    samples = rng.sample(articles, 3)

    lines = [
        "# Ingestion report",
        "",
        f"- Source: DOLE 2022 renumbered edition of PD 442 via ILO NatLex ({SOURCE_URL})",
        f"- Articles parsed: **{len(articles)}**",
        f"- With renumbering annotation (`[old no.]`): **{len(renumbered)}**",
        f"- Article number range: {articles[0].article_no} to {articles[-1].article_no}",
        "",
        "## Articles per book",
        "",
        "| Book | Articles |",
        "| --- | --- |",
        *[f"| {b} | {c} |" for b, c in books.items()],
        "",
        "## Warnings",
        "",
        *([f"- {w}" for w in warnings] or ["- none"]),
        "",
        "## Spot checks (random, seed=42) — verify against the PDF",
        "",
    ]
    for a in samples:
        lines += [
            f"### Art. {a.article_no}" + (f" [{a.old_article_no}]" if a.old_article_no else "") + f" — {a.heading}",
            "",
            f"*{a.breadcrumb}*",
            "",
            "> " + a.body[:600].replace("\n", "\n> "),
            "",
        ]
    (ROOT / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote report.md")


def main() -> None:
    pdf = download()
    lines = extract_body_lines(pdf)
    articles, parse_warnings = parse_articles(lines)
    warnings = parse_warnings + quality_gate(articles)

    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / "articles.json"
    out.write_text(
        json.dumps([a.model_dump() for a in articles], indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"parsed {len(articles)} articles -> {out}")
    for w in warnings:
        print(f"WARNING: {w}")
    write_report(articles, warnings)


if __name__ == "__main__":
    main()
