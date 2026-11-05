"""How well does each search mode find the right note?

For every labelled query a mode returns a ranked list of notes; a note is correct when it is in the query's relevant
set. Two numbers per mode and per kind of query:

* recall@3  the share of queries with a correct note in the first three;
* MRR       the mean of 1 / (position of the first correct note), 0 when there is none.

The evaluation reads documents, not chunks, so a note split in two chunks is not counted twice. Each query is run once
per mode and the results are grouped afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from pulse.search.corpus import QUERIES, LabelledQuery
from pulse.search.embedding import Embedder
from pulse.search.store import MODES, Mode, search


@dataclass(frozen=True)
class Score:
    queries: int
    recall_at_3: float
    mrr: float


def first_correct_rank(ranked_docs: list[str], relevant: frozenset[str]) -> int | None:
    for position, doc_id in enumerate(ranked_docs, start=1):
        if doc_id in relevant:
            return position
    return None


def aggregate(positions: list[int | None]) -> Score:
    n = len(positions)
    if n == 0:
        return Score(0, 0.0, 0.0)
    found = [p for p in positions if p is not None]
    return Score(n, sum(1 for p in found if p <= 3) / n, sum(1.0 / p for p in found) / n)


def positions_for(
    engine: Engine, embedder: Embedder, mode: Mode, queries: tuple[LabelledQuery, ...]
) -> list[int | None]:
    out: list[int | None] = []
    for labelled in queries:
        ranked = list(dict.fromkeys(h.doc_id for h in search(engine, embedder, labelled.query, mode, k=10)))
        out.append(first_correct_rank(ranked, labelled.relevant))
    return out


def evaluate(
    engine: Engine, embedder: Embedder, queries: tuple[LabelledQuery, ...] = QUERIES
) -> dict[str, dict[str, Score]]:
    """{mode: {'all' or a kind: Score}}"""
    kinds = list(dict.fromkeys(q.kind for q in queries))
    table: dict[str, dict[str, Score]] = {}
    for mode in MODES:
        positions = positions_for(engine, embedder, mode, queries)
        row = {"all": aggregate(positions)}
        for kind in kinds:
            row[kind] = aggregate([p for p, q in zip(positions, queries, strict=True) if q.kind == kind])
        table[mode] = row
    return table


def render(table: dict[str, dict[str, Score]]) -> str:
    """The table as plain text: one row per mode, recall@3 and MRR per kind of query."""
    kinds = list(next(iter(table.values())))
    width = 15
    lines = [
        "mode".ljust(10) + "".join(k.rjust(width) for k in kinds),
        "".ljust(10) + "".join("recall@3   MRR".rjust(width) for _ in kinds),
    ]
    for mode, row in table.items():
        lines.append(mode.ljust(10) + "".join(f"{row[k].recall_at_3:>8.2f}{row[k].mrr:>7.2f}" for k in kinds))
    lines.append(
        "queries".ljust(10) + "".join(str(s.queries).rjust(width) for s in next(iter(table.values())).values())
    )
    return "\n".join(lines)
