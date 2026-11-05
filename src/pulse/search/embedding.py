"""A deterministic embedder: hashed character trigrams.

It captures spelling and word forms ("synchronisation" next to "synchronisaton"). It does **not** capture meaning: two
sentences with no letters in common are strangers to it. That is a deliberate trade, so the whole pipeline runs with
no model download and gives the same vectors on every machine; `Embedder` is the seam where a sentence model goes.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Protocol

_STOP_TEXT = (
    "a an and are as at be by do does for from how if in is it its of on or so than that the their then there this to "
    "was we what when where which who why will with"
)
STOP_WORDS = frozenset(_STOP_TEXT.split())
_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float] | None: ...


def words(text: str) -> list[str]:
    """Lower-cased words without accents or stop words."""
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return [w for w in _WORD.findall(plain) if w not in STOP_WORDS]


class HashingNgramEmbedder:
    def __init__(self, dim: int = 256, ngram: int = 3) -> None:
        if dim < 16 or ngram < 2:
            raise ValueError("dim must be at least 16 and ngram at least 2")
        self.dim = dim
        self._n = ngram

    def embed(self, text: str) -> list[float] | None:
        """A unit vector, or None when the text has no usable word (a zero vector has no direction to compare)."""
        vector = [0.0] * self.dim
        seen = False
        for word in words(text):
            padded = f"^{word}$"
            grams = [padded[i : i + self._n] for i in range(max(1, len(padded) - self._n + 1))]
            for gram in grams:
                digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dim
                vector[index] += 1.0 if digest[4] & 1 else -1.0
                seen = True
        norm = math.sqrt(sum(x * x for x in vector))
        if not seen or norm == 0.0:
            return None
        return [x / norm for x in vector]
