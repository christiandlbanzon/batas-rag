"""Pydantic schemas shared across the pipeline and eval harness."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Article(BaseModel):
    """One article of the Labor Code (DOLE renumbered edition)."""

    article_no: str = Field(..., description="Renumbered article number, e.g. '87' or '34-A'")
    old_article_no: Optional[str] = Field(
        None, description="Pre-renumbering number from the '[N]' annotation, if any"
    )
    heading: str = Field(..., description="Article heading, e.g. 'Overtime Work'")
    book: str = Field(..., description="e.g. 'Book Three' or 'Preliminary Title'")
    book_title: str = Field("", description="e.g. 'Conditions of Employment'")
    title: str = Field("", description="Title within the book, e.g. 'Title I — Working Conditions and Rest Periods'")
    chapter: str = Field("", description="Chapter within the title, if any")
    body: str

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("article body is empty")
        return v

    @property
    def breadcrumb(self) -> str:
        parts = [self.book]
        if self.title:
            parts.append(self.title)
        return " > ".join(parts) + f" > Art. {self.article_no} ({self.heading})"


class Chunk(BaseModel):
    """A retrieval unit. Never spans two articles."""

    article_no: str
    chunk_index: int = 0
    content: str  # breadcrumb header + chunk text — exactly what gets embedded
    content_hash: str = ""  # sha256 of content, set by chunk.py


class EvalCase(BaseModel):
    """One golden-set question for the retrieval/answer evals."""

    id: str
    question: str
    expected_article: Optional[str] = Field(
        None, description="Gold article_no; None for out-of-corpus trap questions"
    )
    kind: Literal["direct", "paraphrase", "trap"]
    notes: str = ""
