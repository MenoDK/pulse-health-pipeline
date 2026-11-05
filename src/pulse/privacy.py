"""Proof that an identifier is nowhere: look for it everywhere.

`find_values` walks every text-like column of every table and counts the rows that contain any of the given values. It
reports how many columns it examined, because a scan that looked at nothing proves nothing (and a test plants a value
to check the scan can see it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import Engine, text

TEXT_TYPES = ("text", "character varying", "character", "jsonb", "json")


@dataclass(frozen=True)
class ScanResult:
    columns_examined: int
    matches: tuple[tuple[str, str, int], ...]  # (table, column, rows that contain a value)

    @property
    def clean(self) -> bool:
        return not self.matches


def find_values(engine: Engine, values: list[str]) -> ScanResult:
    pattern = "|".join(re.escape(v) for v in values if v)
    if not pattern:
        raise ValueError("nothing to look for")
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND data_type = ANY(:types) ORDER BY 1, 2"
            ),
            {"types": list(TEXT_TYPES)},
        ).all()
        found: list[tuple[str, str, int]] = []
        for table, column in columns:
            n = conn.execute(
                text(f"SELECT count(*) FROM {quote(table)} WHERE CAST({quote(column)} AS text) ~ :pattern"),  # noqa: S608
                {"pattern": pattern},
            ).scalar()
            if n:
                found.append((table, column, int(n)))
    return ScanResult(len(columns), tuple(found))
