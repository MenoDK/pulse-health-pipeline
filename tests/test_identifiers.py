from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pulse.identifiers import Pseudonymizer, digits_only, is_valid_national_id, with_check_digits


def test_check_digits_make_an_identifier_valid_and_a_changed_digit_invalid() -> None:
    valid = with_check_digits("123456789")
    assert is_valid_national_id(valid)
    last = int(valid[-1])
    assert not is_valid_national_id(valid[:-1] + str((last + 1) % 10))


def test_punctuation_is_ignored_when_validating() -> None:
    valid = with_check_digits("987654321")
    assert is_valid_national_id(f"{valid[:3]}.{valid[3:6]}.{valid[6:9]}-{valid[9:]}")


@pytest.mark.parametrize("bad", ["", "123", "00000000000", "11111111111", "1234567890", "123456789012", "abcdefghijk"])
def test_malformed_identifiers_are_invalid(bad: str) -> None:
    assert not is_valid_national_id(bad)


@given(st.text(alphabet="0123456789", min_size=9, max_size=9).filter(lambda s: len(set(s)) > 1))
def test_every_completed_identifier_validates(base: str) -> None:
    assert is_valid_national_id(with_check_digits(base))


def test_with_check_digits_refuses_the_wrong_length() -> None:
    with pytest.raises(ValueError, match="nine digits"):
        with_check_digits("12345")


def test_digits_only() -> None:
    assert digits_only("12.3-4 5") == "12345"


def test_a_pseudonym_is_stable_keyed_and_tagged() -> None:
    a = Pseudonymizer("0123456789abcdef-key-one", "k1")
    b = Pseudonymizer("0123456789abcdef-key-two", "k1")
    assert a.subject_key("reg-p-1") == a.subject_key("reg-p-1")
    assert a.subject_key("reg-p-1") != a.subject_key("reg-p-2")
    assert a.subject_key("reg-p-1") != b.subject_key("reg-p-1")  # a different key gives a different pseudonym
    assert a.subject_key("reg-p-1").startswith("pk1.")


def test_a_pseudonym_does_not_contain_the_identifier_and_ignores_surrounding_space() -> None:
    p = Pseudonymizer("0123456789abcdef-key-one", "k1")
    assert "reg-p-000042" not in p.subject_key("reg-p-000042")
    assert p.subject_key("  reg-p-000042 ") == p.subject_key("reg-p-000042")


def test_the_key_id_tags_the_pseudonym_so_a_rotation_can_tell_old_from_new() -> None:
    old = Pseudonymizer("0123456789abcdef-key-one", "k1").subject_key("x")
    new = Pseudonymizer("0123456789abcdef-key-one", "k2").subject_key("x")
    assert old.split(".")[0] == "pk1" and new.split(".")[0] == "pk2"


@pytest.mark.parametrize(
    ("key", "key_id"), [("short", "k1"), ("0123456789abcdef-ok", ""), ("0123456789abcdef-ok", "has space")]
)
def test_a_weak_key_or_an_odd_key_id_is_refused(key: str, key_id: str) -> None:
    with pytest.raises(ValueError, match="key"):
        Pseudonymizer(key, key_id)


def test_an_empty_identifier_cannot_be_pseudonymised() -> None:
    with pytest.raises(ValueError, match="empty"):
        Pseudonymizer("0123456789abcdef-key-one", "k1").subject_key("   ")
