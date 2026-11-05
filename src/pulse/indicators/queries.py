"""The counts behind each indicator, as SQL parameterised on the date of the report.

Every window is written out: age is whole months between the birth month and the report month, and a window is
"after as_of minus N months, up to and including as_of". An encounter in the future of the report date is not counted,
and neither is a withdrawn (deleted) one. `tests/reference.py` recomputes the same counts in plain Python from the
rows, and a test compares the two over random data.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction

from sqlalchemy import Connection, text

from pulse.indicators.scoring import IndicatorDef

INDICATORS: tuple[IndicatorDef, ...] = (
    IndicatorDef(
        "chronic-follow-up",
        "Chronic conditions followed up",
        "People with a chronic condition who had a consultation in the last 12 months.",
        2,
        Fraction(7, 10),
    ),
    IndicatorDef(
        "child-checkups",
        "Young children with their check-ups",
        "Children under 24 months with at least three check-ups.",
        2,
        Fraction(3, 4),
    ),
    IndicatorDef(
        "adult-screening",
        "Adults screened",
        "People aged 25 to 64 with a screening in the last 36 months.",
        1,
        Fraction(3, 5),
    ),
    IndicatorDef(
        "registry-fresh",
        "Registrations kept up to date",
        "People whose registration was refreshed in the last 24 months.",
        1,
        Fraction(4, 5),
    ),
    IndicatorDef(
        "elder-home-visits",
        "Older people visited at home",
        "People aged 65 and over with a home visit in the last 12 months.",
        1,
        Fraction(11, 20),
    ),
)

_BASE = """
WITH s AS (
  SELECT subject_key, chronic, registry_refreshed_on,
         (EXTRACT(YEAR FROM CAST(:as_of AS date)) * 12 + EXTRACT(MONTH FROM CAST(:as_of AS date)))
         - (EXTRACT(YEAR FROM birth_month) * 12 + EXTRACT(MONTH FROM birth_month)) AS age_months
  FROM subjects
  WHERE NOT deleted AND birth_month <= CAST(:as_of AS date)
),
e AS (
  SELECT subject_key, kind, occurred_on FROM encounters
  WHERE NOT deleted AND occurred_on <= CAST(:as_of AS date)
)
"""

_COUNTS: dict[str, str] = {
    "chronic-follow-up": """
        SELECT count(*) AS den,
               count(*) FILTER (WHERE EXISTS (
                 SELECT 1 FROM e WHERE e.subject_key = s.subject_key AND e.kind = 'consultation'
                   AND e.occurred_on > CAST(:as_of AS date) - interval '12 months')) AS num
        FROM s WHERE s.chronic""",
    "child-checkups": """
        SELECT count(*) AS den,
               count(*) FILTER (WHERE (
                 SELECT count(*) FROM e WHERE e.subject_key = s.subject_key AND e.kind = 'checkup'
                   AND e.occurred_on > CAST(:as_of AS date) - interval '24 months') >= 3) AS num
        FROM s WHERE s.age_months < 24""",
    "adult-screening": """
        SELECT count(*) AS den,
               count(*) FILTER (WHERE EXISTS (
                 SELECT 1 FROM e WHERE e.subject_key = s.subject_key AND e.kind = 'screening'
                   AND e.occurred_on > CAST(:as_of AS date) - interval '36 months')) AS num
        FROM s WHERE s.age_months >= 300 AND s.age_months < 780""",
    "registry-fresh": """
        SELECT count(*) AS den,
               count(*) FILTER (WHERE s.registry_refreshed_on > CAST(:as_of AS date) - interval '24 months') AS num
        FROM s""",
    "elder-home-visits": """
        SELECT count(*) AS den,
               count(*) FILTER (WHERE EXISTS (
                 SELECT 1 FROM e WHERE e.subject_key = s.subject_key AND e.kind = 'home-visit'
                   AND e.occurred_on > CAST(:as_of AS date) - interval '12 months')) AS num
        FROM s WHERE s.age_months >= 780""",
}


def counts(conn: Connection, as_of: date) -> dict[str, tuple[int, int]]:
    """(numerator, denominator) for every indicator, from one snapshot of the data."""
    found: dict[str, tuple[int, int]] = {}
    for code, body in _COUNTS.items():
        row = conn.execute(text(_BASE + body), {"as_of": as_of}).one()
        found[code] = (int(row.num), int(row.den))
    return found
