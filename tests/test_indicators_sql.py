"""The SQL behind the indicators against a plain-Python reference, over random data built to sit on every edge."""

from __future__ import annotations

import random
import threading
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, text

from pulse.indicators import report as report_module
from pulse.indicators.queries import INDICATORS, counts
from pulse.indicators.report import build_report
from tests.reference import minus_months, months_between, reference_counts

pytestmark = pytest.mark.integration

STAMP = datetime(2026, 1, 1, tzinfo=UTC)
KINDS = ("consultation", "checkup", "screening", "home-visit", "vaccination")
# Month ends and a leap day: where "N months before" has to clamp.
AS_OF_DATES = [
    date(2026, 6, 30),
    date(2026, 3, 31),
    date(2026, 2, 28),
    date(2028, 2, 29),
    date(2026, 7, 15),
    date(2027, 1, 1),
]
AGE_EDGES = (0, 1, 23, 24, 25, 299, 300, 301, 779, 780, 781)


def put(db: Engine, subjects: list[dict[str, Any]], encounters: list[dict[str, Any]]) -> None:
    with db.begin() as conn:
        if subjects:
            conn.execute(
                text(
                    "INSERT INTO subjects (subject_key, key_id, birth_month, chronic, registered_on, registry_refreshed_on, version, deleted, source_updated_at) "
                    "VALUES (:subject_key, 't1', :birth_month, :chronic, :registered_on, :registry_refreshed_on, 1, :deleted, :stamp)"
                ),
                [{**s, "stamp": STAMP} for s in subjects],
            )
        if encounters:
            conn.execute(
                text(
                    "INSERT INTO encounters (encounter_id, subject_key, kind, occurred_on, version, deleted, source_updated_at) "
                    "VALUES (:encounter_id, :subject_key, :kind, :occurred_on, 1, :deleted, :stamp)"
                ),
                [{**e, "stamp": STAMP} for e in encounters],
            )


def person(
    key: str,
    as_of: date,
    age_months: int,
    *,
    chronic: bool = False,
    refreshed: date | None = None,
    deleted: bool = False,
) -> dict[str, Any]:
    birth = minus_months(as_of.replace(day=1), age_months)
    return {
        "subject_key": key,
        "birth_month": birth,
        "chronic": chronic,
        "registered_on": birth,
        "registry_refreshed_on": refreshed or as_of,
        "deleted": deleted,
    }


def encounter(n: int, key: str, kind: str, day: date, *, deleted: bool = False) -> dict[str, Any]:
    return {"encounter_id": f"e{n:05d}", "subject_key": key, "kind": kind, "occurred_on": day, "deleted": deleted}


def random_world(rnd: random.Random, as_of: date, size: int = 160) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    subjects: list[dict[str, Any]] = []
    encounters: list[dict[str, Any]] = []
    for i in range(size):
        age = rnd.choice(AGE_EDGES) if rnd.random() < 0.5 else rnd.randint(0, 1200)
        if rnd.random() < 0.03:
            age = -rnd.randint(1, 6)  # born after the report date
        refreshed = minus_months(as_of, 24)
        refreshed = refreshed.replace(day=min(28, refreshed.day))
        offsets = rnd.choice([-1, 0, 1]) if rnd.random() < 0.5 else rnd.randint(-900, 200)
        refreshed = date.fromordinal(refreshed.toordinal() + offsets)
        key = f"s{i:04d}"
        subjects.append(
            person(key, as_of, age, chronic=rnd.random() < 0.4, refreshed=refreshed, deleted=rnd.random() < 0.05)
        )
        for _ in range(rnd.randint(0, 6)):
            kind = rnd.choice(KINDS)
            window = {"consultation": 12, "checkup": 24, "screening": 36, "home-visit": 12}.get(kind, 12)
            edge = minus_months(as_of, window)
            if rnd.random() < 0.5:
                day = date.fromordinal(edge.toordinal() + rnd.choice([-1, 0, 1]))
            elif rnd.random() < 0.1:
                day = date.fromordinal(as_of.toordinal() + rnd.randint(1, 40))  # after the report date
            else:
                day = date.fromordinal(as_of.toordinal() - rnd.randint(0, 1500))
            encounters.append(encounter(len(encounters), key, kind, day, deleted=rnd.random() < 0.05))
    return subjects, encounters


@pytest.mark.parametrize("seed", range(30))
def test_the_sql_agrees_with_the_plain_python_reference_on_random_data(db: Engine, seed: int) -> None:
    rnd = random.Random(seed)
    as_of = AS_OF_DATES[seed % len(AS_OF_DATES)]
    subjects, encounters = random_world(rnd, as_of)
    put(db, subjects, encounters)
    with db.connect() as conn:
        actual = counts(conn, as_of)
    expected = reference_counts(subjects, encounters, as_of)
    assert actual == expected
    assert sum(den for _, den in expected.values()) > 0  # the world was not empty


def test_the_random_worlds_really_reach_both_sides_of_every_edge(db: Engine) -> None:
    """A differential test is only as good as its data: across the seeds, every indicator has people in and out of it."""
    reached: dict[str, set[bool]] = {d.code: set() for d in INDICATORS}
    for seed in range(30):
        as_of = AS_OF_DATES[seed % len(AS_OF_DATES)]
        subjects, encounters = random_world(random.Random(seed), as_of)
        for code, (num, den) in reference_counts(subjects, encounters, as_of).items():
            if num:
                reached[code].add(True)
            if den - num:
                reached[code].add(False)
    assert all(sides == {True, False} for sides in reached.values()), reached


# ---- hand-computed cases: the reference could share a misunderstanding with the SQL, these do not -----------------

AS_OF = date(2026, 6, 30)


def one(db: Engine, code: str) -> tuple[int, int]:
    with db.connect() as conn:
        return counts(conn, AS_OF)[code]


def test_a_consultation_exactly_twelve_months_ago_is_outside_the_window_and_a_day_later_is_inside(db: Engine) -> None:
    put(
        db,
        [person("a", AS_OF, 400, chronic=True), person("b", AS_OF, 400, chronic=True)],
        [
            encounter(1, "a", "consultation", date(2025, 6, 30)),  # exactly 12 months: "after", so out
            encounter(2, "b", "consultation", date(2025, 7, 1)),  # a day inside
        ],
    )
    assert one(db, "chronic-follow-up") == (1, 2)


def test_the_window_clamps_at_the_end_of_a_short_month(db: Engine) -> None:
    as_of = date(2026, 3, 31)  # 12 months back is 31 March 2025; 24 months back for the registry is also exact
    put(
        db,
        [person("a", as_of, 400, chronic=True), person("b", as_of, 400, chronic=True)],
        [
            encounter(1, "a", "consultation", date(2025, 3, 31)),
            encounter(2, "b", "consultation", date(2025, 4, 1)),
        ],
    )
    with db.connect() as conn:
        assert counts(conn, as_of)["chronic-follow-up"] == (1, 2)
    assert minus_months(date(2026, 3, 31), 1) == date(2026, 2, 28)  # and the helper itself clamps
    assert minus_months(date(2028, 3, 31), 1) == date(2028, 2, 29)


def test_a_child_needs_three_checkups_in_two_years_and_the_age_line_is_exact(db: Engine) -> None:
    put(
        db,
        [person("young", AS_OF, 23), person("edge", AS_OF, 24), person("two", AS_OF, 10)],
        [
            *[encounter(i, "young", "checkup", date(2026, 1, 10 + i)) for i in range(3)],
            *[
                encounter(10 + i, "edge", "checkup", date(2026, 1, 10 + i)) for i in range(3)
            ],  # 24 months old: not a young child
            *[encounter(20 + i, "two", "checkup", date(2026, 1, 10 + i)) for i in range(2)],  # only two
        ],
    )
    assert one(db, "child-checkups") == (1, 2)  # young (met) and two (not met); edge is outside the group


def test_the_adult_band_includes_twenty_five_and_excludes_sixty_five(db: Engine) -> None:
    put(
        db,
        [person("t24", AS_OF, 299), person("t25", AS_OF, 300), person("t64", AS_OF, 779), person("t65", AS_OF, 780)],
        [],
    )
    assert one(db, "adult-screening") == (0, 2)  # 25 and 64 years in, 24 and 65 out
    assert one(db, "elder-home-visits") == (0, 1)  # 65 only


def test_withdrawn_people_and_withdrawn_visits_do_not_count_and_future_ones_do_not_either(db: Engine) -> None:
    put(
        db,
        [person("live", AS_OF, 800), person("gone", AS_OF, 800, deleted=True), person("unborn", AS_OF, -2)],
        [
            encounter(1, "live", "home-visit", date(2026, 7, 5)),  # after the report date
            encounter(2, "live", "home-visit", date(2026, 5, 5), deleted=True),
            encounter(3, "gone", "home-visit", date(2026, 5, 5)),
        ],
    )
    assert one(db, "elder-home-visits") == (0, 1)
    assert one(db, "registry-fresh") == (1, 1)  # the unborn and the withdrawn are not people yet / any more


def test_nothing_in_the_database_is_no_data_and_not_zero_percent(db: Engine) -> None:
    report = build_report(db, AS_OF).to_dict()
    assert report["score"] is None
    assert report["indicators_with_data"] == 0
    assert {i["status"] for i in report["indicators"]} == {"no-data"}


def test_people_with_nobody_in_the_group_are_excluded_from_the_score(db: Engine) -> None:
    put(
        db, [person("only", AS_OF, 400)], []
    )  # an adult with no screening: the screening and registry indicators have a denominator
    report = build_report(db, AS_OF).to_dict()
    by_code = {i["code"]: i for i in report["indicators"]}
    assert by_code["adult-screening"]["denominator"] == 1 and by_code["adult-screening"]["status"] == "critical"
    assert by_code["child-checkups"]["status"] == "no-data"
    assert "child-checkups" in report["excluded"]


def test_all_five_counts_come_from_one_snapshot(db: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sync that commits while the report is being computed must not be half in it."""
    put(db, [person("a", AS_OF, 400, chronic=True)], [])
    real = report_module.counts
    seen: dict[str, Any] = {}

    def counts_then_a_commit_from_elsewhere(conn: Any, as_of: date) -> Any:
        first = real(conn, as_of)
        writer = threading.Thread(target=lambda: put(db, [person("late", AS_OF, 400, chronic=True)], []))
        writer.start()
        writer.join(10)  # committed, in another connection, before the second read below
        seen["second"] = real(conn, as_of)
        return first

    monkeypatch.setattr(report_module, "counts", counts_then_a_commit_from_elsewhere)
    build_report(db, AS_OF)
    assert seen["second"]["chronic-follow-up"] == (0, 1)  # the late arrival is invisible inside the snapshot
    with db.connect() as conn:
        assert counts(conn, AS_OF)["chronic-follow-up"] == (0, 2)  # and visible to the next report


def test_helpers_agree_with_the_calendar() -> None:
    assert months_between(date(2024, 1, 1), date(2026, 7, 1)) == 30
    assert months_between(date(2026, 7, 1), date(2026, 7, 1)) == 0
