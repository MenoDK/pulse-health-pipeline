"""Identifiers: a checksum for the national identifier and a keyed pseudonym for everything stored.

The registry sends a national identifier (11 digits, the last two are check digits) and an opaque person id. The
pipeline checks the first and stores neither: an analytic table holds a keyed hash of the person id, so a leaked copy
of the analytic layer cannot be joined back to the registry without the key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

_DIGITS = re.compile(r"\D+")


def digits_only(value: str) -> str:
    return _DIGITS.sub("", value)


def _check_digit(digits: str) -> int:
    weight = len(digits) + 1
    total = sum(int(d) * w for d, w in zip(digits, range(weight, 1, -1), strict=True))
    remainder = (total * 10) % 11
    return 0 if remainder == 10 else remainder


def with_check_digits(base9: str) -> str:
    """Complete nine digits with their two check digits. Used by the synthetic generator."""
    if len(base9) != 9 or not base9.isdigit():
        raise ValueError("expected exactly nine digits")
    first = _check_digit(base9)
    second = _check_digit(base9 + str(first))
    return base9 + str(first) + str(second)


def is_valid_national_id(value: str) -> bool:
    digits = digits_only(value)
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    return with_check_digits(digits[:9]) == digits


class Pseudonymizer:
    """HMAC-SHA256 of a normalised identifier, truncated to 130 bits and tagged with the id of the key that made it.

    The tag is what makes a rotation possible: rows made with the old key keep their tag, so a re-keying job could find
    them (that job is not part of this repository). The hash is keyed on purpose: a plain hash of an identifier with a
    small space can be reversed by trying every value.
    """

    def __init__(self, key: str, key_id: str) -> None:
        if len(key) < 16:
            raise ValueError("the pseudonymisation key must be at least 16 characters")
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", key_id):
            raise ValueError("the key id must be 1 to 16 letters or digits")
        self._key = key.encode()
        self.key_id = key_id

    def subject_key(self, registry_person_id: str) -> str:
        normalised = registry_person_id.strip()
        if not normalised:
            raise ValueError("an empty identifier cannot be pseudonymised")
        digest = hmac.new(self._key, b"subject\x00" + normalised.encode(), hashlib.sha256).digest()
        token = base64.b32encode(digest[:17]).decode().rstrip("=").lower()[:26]
        return f"p{self.key_id}.{token}"
