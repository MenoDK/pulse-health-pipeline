"""The deterministic embedder: what it captures (spelling) and, stated as tests, what it does not (meaning)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pulse.search.embedding import STOP_WORDS, HashingNgramEmbedder, words

E = HashingNgramEmbedder()


def cosine(a: str, b: str) -> float:
    x, y = E.embed(a), E.embed(b)
    assert x is not None and y is not None
    return sum(i * j for i, j in zip(x, y, strict=True))


def test_the_same_text_gives_the_same_vector_on_every_call_and_every_instance() -> None:
    assert E.embed("synchronisation") == E.embed("synchronisation") == HashingNgramEmbedder().embed("synchronisation")


def test_a_vector_has_the_configured_size_and_unit_length() -> None:
    vector = E.embed("a transmission queue that survives crashes")
    assert vector is not None
    assert len(vector) == E.dim == 256
    assert math.sqrt(sum(x * x for x in vector)) == pytest.approx(1.0)


def test_case_accents_and_stop_words_do_not_change_the_vector() -> None:
    assert E.embed("Café Registry") == E.embed("cafe registry") == E.embed("the cafe of the registry")


def test_text_with_nothing_to_compare_has_no_vector_instead_of_a_zero_one() -> None:
    assert E.embed("") is None
    assert E.embed("   ") is None
    assert E.embed("the of and to") is None  # only stop words
    assert E.embed("!!! ???") is None


def test_spelling_is_captured_a_typo_stays_close_and_a_stranger_does_not() -> None:
    assert cosine("synchronisation", "synchronisaton") > 0.6
    assert cosine("synchronisation", "synchronisation") == pytest.approx(1.0)
    assert cosine("synchronisation", "gateway") < 0.25


def test_word_forms_are_closer_than_unrelated_words() -> None:
    assert cosine("retry", "retries") > cosine("retry", "pseudonym")


def test_meaning_is_not_captured_and_this_test_is_the_proof() -> None:
    """Synonyms with no letters in common look like strangers. The README lists this as a limit; a sentence model is the fix."""
    assert cosine("doctor", "physician") < 0.3
    assert cosine("doctor", "doctors") > 0.5


def test_the_vectors_are_the_ones_the_index_was_built_with() -> None:
    """Pinned on purpose: stored vectors and query vectors must come from the same scheme (hash, trigram, and the
    `^` and `$` that mark where a word starts and ends). Change any of it and `pulse index` has to be run again."""
    lock = E.embed("lock")  # four trigrams: ^lo loc ock ck$
    assert lock is not None
    assert {i: x for i, x in enumerate(lock) if x} == {7: -0.5, 76: 0.5, 89: -0.5, 202: -0.5}
    retries = E.embed("retries")
    assert retries is not None
    assert {i: round(x, 6) for i, x in enumerate(retries) if x} == {
        3: 0.377964,
        38: -0.377964,
        74: 0.377964,
        78: 0.377964,
        187: -0.377964,
        201: 0.377964,
        217: 0.377964,
    }


def test_the_start_and_end_of_a_word_are_part_of_its_spelling() -> None:
    # Without the markers "lock" would be nearly contained in "block" (0.82); with them they share three of five (0.67).
    assert cosine("lock", "block") < 0.75


def test_a_single_character_word_still_gets_a_vector() -> None:
    assert E.embed("x") is not None  # '^x$' is shorter than a trigram window


@pytest.mark.parametrize(("dim", "ngram"), [(8, 3), (256, 1)])
def test_silly_settings_are_refused(dim: int, ngram: int) -> None:
    with pytest.raises(ValueError, match="dim"):
        HashingNgramEmbedder(dim, ngram)


def test_words_lowercases_strips_accents_and_drops_stop_words() -> None:
    assert words("The Résumé of THE Café, 2026!") == ["resume", "cafe", "2026"]
    assert "the" in STOP_WORDS


@given(st.text(max_size=80))
def test_any_text_gives_either_no_vector_or_a_unit_vector_and_never_raises(text: str) -> None:
    vector = E.embed(text)
    if vector is not None:
        assert len(vector) == 256
        assert math.sqrt(sum(x * x for x in vector)) == pytest.approx(1.0)
