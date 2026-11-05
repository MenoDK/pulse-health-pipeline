"""Indexing and searching the knowledge base in PostgreSQL (pgvector + full-text)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import Engine, text

from pulse.search.corpus import DOCS, Doc
from pulse.search.embedding import Embedder, words
from pulse.search.fusion import rrf, weighted

Mode = Literal["lexical", "vector", "hybrid", "weighted"]
MODES: tuple[Mode, ...] = ("lexical", "vector", "hybrid", "weighted")
POOL = 20  # how deep each list is read before they are fused
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Hit:
    doc_id: str
    chunk_no: int
    title: str
    category: str
    snippet: str
    score: float
    ranks: dict[str, int] = field(default_factory=dict)  # the position in each list that produced it


def chunk_text(content: str, *, size: int = 600, overlap: int = 100) -> list[str]:
    """Split on word boundaries into pieces of about `size` characters that share `overlap` characters."""
    if size <= overlap or overlap < 0:
        raise ValueError("size must exceed overlap, and overlap must not be negative")
    tokens = content.split()
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end, length = start, 0
        while end < len(tokens) and (length + len(tokens[end]) + 1 <= size or end == start):
            length += len(tokens[end]) + 1
            end += 1
        chunks.append(" ".join(tokens[start:end]))
        if end >= len(tokens):
            break
        back, kept = end, 0
        while back > start + 1 and kept + len(tokens[back - 1]) + 1 <= overlap:
            back -= 1
            kept += len(tokens[back]) + 1
        start = max(back, start + 1)
    return chunks


def lexical_query(query: str) -> str | None:
    """A tsquery matching any of the words (OR), built from letters and digits only: input cannot inject syntax."""
    terms = list(dict.fromkeys(w for w in words(query) if _TOKEN.fullmatch(w)))
    return " | ".join(terms) if terms else None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"


def index_documents(engine: Engine, embedder: Embedder, docs: tuple[Doc, ...] = DOCS) -> int:
    """Insert or refresh every chunk. Safe to run again: a chunk is keyed by (doc_id, chunk_no)."""
    count = 0
    with engine.begin() as conn:
        for doc in docs:
            for number, chunk in enumerate(chunk_text(doc.text)):
                vector = embedder.embed(f"{doc.title} {chunk}")
                if vector is None:
                    continue
                conn.execute(
                    text(
                        "INSERT INTO kb_chunks (doc_id, chunk_no, title, category, content, embedding) "
                        "VALUES (:d, :n, :t, :c, :x, CAST(:e AS vector)) "
                        "ON CONFLICT (doc_id, chunk_no) DO UPDATE SET title = excluded.title, "
                        "  category = excluded.category, content = excluded.content, embedding = excluded.embedding"
                    ),
                    {
                        "d": doc.doc_id,
                        "n": number,
                        "t": doc.title,
                        "c": doc.category,
                        "x": chunk,
                        "e": _vector_literal(vector),
                    },
                )
                count += 1
    return count


def _lexical(engine: Engine, query: str, limit: int) -> list[tuple[str, int, str, str, str, float]]:
    q = lexical_query(query)
    if q is None:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT doc_id, chunk_no, title, category, content, ts_rank_cd(tsv, query) AS score "
                "FROM kb_chunks, to_tsquery('english', :q) AS query WHERE tsv @@ query "
                "ORDER BY score DESC, doc_id, chunk_no LIMIT :limit"
            ),
            {"q": q, "limit": limit},
        ).all()
    return [(r.doc_id, r.chunk_no, r.title, r.category, r.content, float(r.score)) for r in rows]


def _vector(engine: Engine, embedder: Embedder, query: str, limit: int) -> list[tuple[str, int, str, str, str, float]]:
    vector = embedder.embed(query)
    if vector is None:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT doc_id, chunk_no, title, category, content, 1 - (embedding <=> CAST(:v AS vector)) AS score "
                "FROM kb_chunks ORDER BY embedding <=> CAST(:v AS vector), doc_id, chunk_no LIMIT :limit"
            ),
            {"v": _vector_literal(vector), "limit": limit},
        ).all()
    return [(r.doc_id, r.chunk_no, r.title, r.category, r.content, float(r.score)) for r in rows]


def search(
    engine: Engine, embedder: Embedder, query: str, mode: Mode = "hybrid", *, k: int = 5, rrf_k: int = 60
) -> list[Hit]:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    if not 1 <= k <= 50:
        raise ValueError("k must be between 1 and 50")
    lexical = _lexical(engine, query, POOL) if mode != "vector" else []
    vector = _vector(engine, embedder, query, POOL) if mode != "lexical" else []

    rows = {(r[0], r[1]): r for r in [*lexical, *vector]}
    lex_rank = {(r[0], r[1]): i for i, r in enumerate(lexical, start=1)}
    vec_rank = {(r[0], r[1]): i for i, r in enumerate(vector, start=1)}

    if mode == "lexical":
        ordered = [((r[0], r[1]), r[5]) for r in lexical]
    elif mode == "vector":
        ordered = [((r[0], r[1]), r[5]) for r in vector]
    elif mode == "hybrid":
        ordered = rrf([[(r[0], r[1]) for r in lexical], [(r[0], r[1]) for r in vector]], k=rrf_k)
    else:
        ordered = weighted({(r[0], r[1]): r[5] for r in vector}, {(r[0], r[1]): r[5] for r in lexical})

    hits = []
    for key, score in ordered[:k]:
        _, chunk_no, title, category, content, _ = rows[key]
        ranks = {
            name: ranking[key] for name, ranking in (("lexical", lex_rank), ("vector", vec_rank)) if key in ranking
        }
        hits.append(Hit(key[0], chunk_no, title, category, content[:240], round(score, 6), ranks))
    return hits
