"""Combining ranked lists.

Reciprocal rank fusion scores an item by the sum, over the lists it appears in, of 1 / (k + rank). It looks only at
positions, so a keyword score and a vector similarity, which live on unrelated scales, can be combined without
inventing a conversion between them. The weighted sum of raw scores is kept next to it as the baseline that the
evaluation measures it against.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import TypeVar

K = TypeVar("K", bound=Hashable)


def rrf(rankings: Sequence[Sequence[K]], *, k: int = 60) -> list[tuple[K, float]]:
    """Best first. Ties are broken by the item itself so the order is the same on every run."""
    if k < 1:
        raise ValueError("k must be at least 1")
    scores: dict[K, float] = {}
    for ranking in rankings:
        for position, item in enumerate(dict.fromkeys(ranking), start=1):  # first occurrence only
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))


def weighted(
    vector: dict[K, float], lexical: dict[K, float], *, vector_weight: float = 0.7, lexical_weight: float = 0.3
) -> list[tuple[K, float]]:
    """The common alternative: a weighted sum of the raw scores, a missing score counting as zero."""
    scores = {
        item: vector_weight * vector.get(item, 0.0) + lexical_weight * lexical.get(item, 0.0)
        for item in {*vector, *lexical}
    }
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))
