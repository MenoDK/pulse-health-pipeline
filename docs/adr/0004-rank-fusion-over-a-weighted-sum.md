# ADR 0004: Rank fusion over a weighted sum

Status: Accepted

## Context
The knowledge base is searched two ways: PostgreSQL full-text (`ts_rank_cd`, exact words) and a vector index (cosine
over hashed character trigrams, which forgives a typo but knows nothing about meaning). Each finds what the other
misses. Their scores are on different scales, so they cannot be added as they are.

## Decision
**Reciprocal Rank Fusion**: a document's score is the sum of `1 / (k + rank)` over the lists it appears in, with
`k = 60` (`SEARCH_RRF_K`). Only ranks are used.

It was measured, not assumed. The queries were written and fixed before the first evaluation, in five kinds (an exact
rare term, a typo, another word form, a question that shares **no** word with the note, a full sentence), over 36 short
notes, and judged on the top three results:

| method | recall@3 | MRR |
| --- | --- | --- |
| lexical only | 0.89 | 0.84 |
| vector only | 0.86 | 0.82 |
| **hybrid (RRF)** | **0.94** | 0.87 |
| weighted sum of the raw scores (0.7 vector + 0.3 lexical) | 0.94 | 0.88 |

Reproduce with `make eval` (it prints the matrix, per kind of query, from the real database).

## Rejected alternatives
- **A weighted sum of the raw scores.** On this evaluation it **ties** RRF (0.94 recall; 0.88 against 0.87 MRR, which
  is not a difference 36 queries can support). It was not chosen because its two scores live on different scales
  (`ts_rank_cd` and a cosine), so the weights mean something only for the corpus they were set on, and a different
  corpus or retriever would need them set again. RRF has one constant from the literature and no scale to calibrate.
  This is a judgement about robustness, **not** a measured win, and the README says so.
- **Lexical only.** Cheapest, and the best single method here, but it fails every typo.
- **Vector only.** Forgives typos, but it captures spelling and not meaning, so it cannot bridge a "gap" query (no
  word in common with the note).
- **A cross-encoder re-ranker.** A model download and a latency cost that this corpus size does not justify.

## Consequences
- (+) Hybrid beats either single method on recall; it never needs retuning when a retriever is swapped.
- (+) The weak spot is visible, not hidden: the "gap" kind is the weakest for every method, and the evaluation prints it.
- (−) The embedder captures spelling, not meaning. A sentence model behind the same `Embedder` interface is the real
  fix, and the weakest groups show where it would pay.
- (−) 36 queries are enough to compare methods, not to claim a production recall figure.
