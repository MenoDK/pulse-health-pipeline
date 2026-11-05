"""Chunking, query building and the search itself, on a real PostgreSQL with pgvector and full-text search."""

from __future__ import annotations

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import Engine, text

from pulse.search.corpus import DOCS, QUERIES, Doc
from pulse.search.embedding import HashingNgramEmbedder
from pulse.search.evaluate import Score, aggregate, evaluate, first_correct_rank, render
from pulse.search.store import MODES, Mode, chunk_text, index_documents, lexical_query, search

E = HashingNgramEmbedder()

# ---- chunking and query building: no database ------------------------------------------------------------------


def test_a_short_text_is_one_chunk() -> None:
    assert chunk_text("a few words only") == ["a few words only"]
    assert chunk_text("") == []


def test_long_text_is_cut_on_word_boundaries_into_pieces_that_overlap() -> None:
    content = " ".join(f"word{i:03d}" for i in range(200))
    chunks = chunk_text(content, size=120, overlap=30)
    assert len(chunks) > 3
    assert all(len(c) <= 120 for c in chunks)
    for before, after in pairwise(chunks):
        assert set(before.split()) & set(after.split())  # consecutive chunks share words
    assert " ".join(dict.fromkeys(" ".join(chunks).split())) == content  # nothing lost, order kept


def test_a_word_longer_than_the_size_still_makes_progress() -> None:
    chunks = chunk_text("x" * 500 + " tail", size=100, overlap=20)
    assert chunks[0] == "x" * 500 and chunks[-1].endswith("tail")


@pytest.mark.parametrize(("size", "overlap"), [(100, 100), (50, 80), (100, -1)])
def test_a_chunk_size_that_cannot_advance_is_refused(size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="size must exceed overlap"):
        chunk_text("some text", size=size, overlap=overlap)


@given(st.lists(st.text("abcdefgh", min_size=1, max_size=12), min_size=1, max_size=120), st.integers(20, 200))
def test_chunking_always_terminates_covers_every_word_and_never_makes_an_empty_chunk(
    tokens: list[str], size: int
) -> None:
    chunks = chunk_text(" ".join(tokens), size=size, overlap=size // 4)
    assert all(chunks)
    assert chunks[0].split()[0] == tokens[0] and chunks[-1].split()[-1] == tokens[-1]
    assert set(" ".join(chunks).split()) == set(tokens)


def test_a_lexical_query_is_an_or_of_plain_words() -> None:
    assert lexical_query("Why does the retry back off?") == "retry | back | off"
    assert lexical_query("retry retry RETRY") == "retry"


@pytest.mark.parametrize(
    "hostile",
    ["'; DROP TABLE kb_chunks; --", "a & !b | (c <-> d)", "word:* & ('", "\\' OR 1=1", "!!!", "the of and", ""],
)
def test_hostile_input_becomes_words_or_nothing_never_query_syntax(hostile: str) -> None:
    built = lexical_query(hostile)
    assert built is None or all(part.isalnum() for part in built.split(" | "))


# ---- the database ---------------------------------------------------------------------------------------------


@pytest.mark.integration
def test_indexing_stores_every_chunk_and_running_it_again_changes_nothing(db: Engine) -> None:
    first = index_documents(db, E)
    expected = sum(len(chunk_text(d.text)) for d in DOCS)
    assert first == expected >= 36
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM kb_chunks")).scalar() == first
    assert index_documents(db, E) == first
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM kb_chunks")).scalar() == first


@pytest.mark.integration
def test_a_changed_note_is_refreshed_in_place_and_its_text_index_follows_without_a_second_write(db: Engine) -> None:
    original = Doc("kb-x", "Backups", "operations", "Nightly copies of the database are kept for a week.")
    index_documents(db, E, (original,))
    assert [h.doc_id for h in search(db, E, "zebra", "lexical")] == []

    index_documents(
        db, E, (Doc("kb-x", "Backups", "operations", "Nightly copies of the zebra database are kept for a week."),)
    )
    assert [h.doc_id for h in search(db, E, "zebra", "lexical")] == ["kb-x"]
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM kb_chunks WHERE doc_id = 'kb-x'")).scalar() == 1


@pytest.mark.integration
def test_a_note_with_nothing_to_embed_is_skipped_not_stored_as_a_zero_vector(db: Engine) -> None:
    assert index_documents(db, E, (Doc("kb-blank", "the", "x", "of and to"),)) == 0


@pytest.fixture
def indexed(db: Engine) -> Engine:
    index_documents(db, E)
    return db


@pytest.mark.integration
@pytest.mark.parametrize("mode", MODES)
def test_every_mode_finds_a_note_by_a_rare_word_it_contains(indexed: Engine, mode: Mode) -> None:
    hits = search(indexed, E, "advisory lock", mode, k=3)
    assert hits
    assert any("lock" in h.snippet.lower() or "lock" in h.title.lower() for h in hits)


@pytest.mark.integration
def test_a_hybrid_hit_says_which_lists_it_came_from_and_where(indexed: Engine) -> None:
    hits = search(indexed, E, "idempotency key duplicate", "hybrid", k=5)
    assert hits[0].ranks.keys() <= {"lexical", "vector"}
    assert any(set(h.ranks) == {"lexical", "vector"} for h in hits)  # found by both
    assert all(h.score > 0 for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


@pytest.mark.integration
def test_a_typo_is_found_by_the_vector_side_and_missed_by_the_exact_side(indexed: Engine) -> None:
    assert search(indexed, E, "synchronisaton", "lexical") == []  # not a word the text index knows
    top = search(indexed, E, "synchronisaton", "vector", k=3)
    assert any("synchronis" in (h.title + " " + h.snippet).lower() for h in top)  # but its spelling is close enough


@pytest.mark.integration
@pytest.mark.parametrize(
    "query", ["'; DROP TABLE kb_chunks; --", "a & !b | (c <-> d)", "\x00 null", "😀 emoji", "x" * 5000]
)
def test_hostile_or_odd_queries_are_answered_and_leave_the_table_alone(indexed: Engine, query: str) -> None:
    for mode in MODES:
        search(indexed, E, query, mode, k=3)  # must not raise
    with indexed.connect() as conn:
        assert (conn.execute(text("SELECT count(*) FROM kb_chunks")).scalar() or 0) >= 36


@pytest.mark.integration
def test_an_empty_or_stop_word_query_returns_nothing_in_every_mode(indexed: Engine) -> None:
    for query in ("", "   ", "the of and"):
        for mode in MODES:
            assert search(indexed, E, query, mode) == []


@pytest.mark.integration
def test_bad_arguments_are_refused(indexed: Engine) -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        search(indexed, E, "lock", "magic")  # type: ignore[arg-type]
    for k in (0, 51, -1):
        with pytest.raises(ValueError, match="k must"):
            search(indexed, E, "lock", "hybrid", k=k)


@pytest.mark.integration
def test_the_database_builds_the_text_vector_itself_and_the_indexes_exist(indexed: Engine) -> None:
    with indexed.connect() as conn:
        indexes = {r[0] for r in conn.execute(text("SELECT indexdef FROM pg_indexes WHERE tablename = 'kb_chunks'"))}
        generated = conn.execute(
            text(
                "SELECT is_generated FROM information_schema.columns WHERE table_name = 'kb_chunks' AND column_name = 'tsv'"
            )
        ).scalar()
    assert generated == "ALWAYS"
    assert any("hnsw" in d.lower() and "vector_cosine_ops" in d for d in indexes)
    assert any("gin" in d.lower() and "tsv" in d for d in indexes)


# ---- the evaluation ---------------------------------------------------------------------------------------------


def test_the_first_correct_position_and_the_aggregate_are_computed_by_hand() -> None:
    assert first_correct_rank(["a", "b", "c"], frozenset({"c", "z"})) == 3
    assert first_correct_rank(["a"], frozenset({"z"})) is None
    score = aggregate([1, 2, 4, None])
    assert score == Score(4, 0.5, pytest.approx((1 + 0.5 + 0.25) / 4))  # type: ignore[arg-type]
    assert aggregate([]) == Score(0, 0.0, 0.0)


def test_the_labelled_queries_are_fixed_distinct_and_point_at_notes_that_exist() -> None:
    known = {d.doc_id for d in DOCS}
    assert len(QUERIES) == 36
    assert len({q.query for q in QUERIES}) == 36
    assert all(q.relevant and q.relevant <= known for q in QUERIES)
    assert {q.kind for q in QUERIES} == {"exact", "typo", "form", "gap", "natural"}


@pytest.mark.integration
def test_the_measured_numbers_are_the_numbers_the_readme_reports(indexed: Engine) -> None:
    """If this fails, the corpus, the embedder or the fusion changed: re-run `make eval` and update the README."""
    table = evaluate(indexed, E)
    measured = {mode: (row["all"].recall_at_3, row["all"].mrr) for mode, row in table.items()}
    published = {"lexical": (0.89, 0.84), "vector": (0.86, 0.82), "hybrid": (0.94, 0.87), "weighted": (0.94, 0.88)}
    for mode, (recall, mrr) in published.items():
        assert measured[mode][0] == pytest.approx(recall, abs=0.006), mode
        assert measured[mode][1] == pytest.approx(mrr, abs=0.006), mode


@pytest.mark.integration
def test_hybrid_is_better_than_either_single_method_on_recall_and_that_is_all_this_data_can_claim(
    indexed: Engine,
) -> None:
    table = evaluate(indexed, E)
    allq = {mode: row["all"] for mode, row in table.items()}
    assert allq["hybrid"].recall_at_3 > max(allq["lexical"].recall_at_3, allq["vector"].recall_at_3)
    assert allq["hybrid"].mrr > max(allq["lexical"].mrr, allq["vector"].mrr)
    # What it cannot claim: a win over the weighted baseline. On 36 queries they are level on recall@3, and the
    # baseline is ahead on MRR by a hundredth, which is one query moving one place. The README says so.
    assert allq["hybrid"].recall_at_3 == pytest.approx(allq["weighted"].recall_at_3, abs=0.006)
    assert abs(allq["hybrid"].mrr - allq["weighted"].mrr) < 0.03


@pytest.mark.integration
def test_the_gap_queries_are_where_every_method_is_weakest_and_the_table_says_so(indexed: Engine) -> None:
    table = evaluate(indexed, E)
    for mode, row in table.items():
        assert row["gap"].recall_at_3 < row["natural"].recall_at_3, mode
        assert row["gap"].recall_at_3 <= 0.6, mode  # no letters in common: a spelling embedder cannot bridge it
    rendered = render(table)
    assert "hybrid" in rendered and "gap" in rendered and rendered.count("\n") >= 5
