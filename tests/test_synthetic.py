"""The fictitious registry: reproducible, internally consistent, and shaped so the indicators are not all green."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime

from pulse.identifiers import is_valid_national_id
from pulse.records import ENTITY_MODELS
from pulse.synthetic import Dataset, evolve, generate

AS_OF = date(2026, 6, 30)


def test_the_same_seed_gives_the_same_registry_and_another_seed_gives_another() -> None:
    a, b, c = generate(5, 80), generate(5, 80), generate(6, 80)
    assert (a.teams, a.people, a.encounters) == (b.teams, b.people, b.encounters)
    assert a.people != c.people


def test_the_shape_of_the_registry() -> None:
    data = generate(3, 250)
    assert len(data.people) == 250
    assert len(data.teams) == 11
    assert len({t["code"] for t in data.teams}) == 8  # three teams are listed a second time under another id
    assert len({p["id"] for p in data.people}) == 250
    assert len({e["id"] for e in data.encounters}) == len(data.encounters)


def test_every_encounter_points_at_a_person_and_a_team_that_exist() -> None:
    data = generate(3, 250)
    people = {p["id"] for p in data.people}
    codes = {t["code"] for t in data.teams}
    assert all(e["person_id"] in people and e["team_code"] in codes for e in data.encounters)


def test_one_person_in_a_hundred_has_a_wrong_check_digit_and_everyone_else_a_right_one() -> None:
    data = generate(3, 450)
    flags = [is_valid_national_id(p["national_id"]) for p in data.people]
    assert [i for i, ok in enumerate(flags) if not ok] == [0, 100, 200, 300, 400]


def test_every_record_fits_the_model_the_pipeline_validates_with() -> None:
    data = generate(3, 120)
    for entity, model in ENTITY_MODELS.items():
        for record in data.entity(entity):
            model.model_validate(record)


def test_nothing_is_dated_after_the_report_date() -> None:
    data = generate(3, 200)
    assert all(date.fromisoformat(e["occurred_on"]) <= AS_OF for e in data.encounters)
    assert all(date.fromisoformat(p["birth_date"]) < AS_OF for p in data.people)
    assert all(
        datetime.fromisoformat(r["updated_at"]).date() <= AS_OF for r in [*data.people, *data.encounters, *data.teams]
    )


def test_names_and_national_identifiers_are_made_up_not_taken_from_anywhere() -> None:
    data = generate(3, 100)
    assert all((p["name"].replace(" ", "").isalpha() and p["name"].istitle()) or " " in p["name"] for p in data.people)
    assert len({p["national_id"] for p in data.people}) > 95  # random, not a pattern


# ---- evolve --------------------------------------------------------------------------------------------------

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def test_evolve_adds_changes_and_withdraws_and_stamps_what_it_touches() -> None:
    data = generate(3, 100)
    before = {e["id"]: dict(e) for e in data.encounters}
    touched = evolve(data, random.Random(1), NOW, new=5, changed=4, removed=2)
    assert touched == 11
    added = [e for e in data.encounters if e["id"] not in before]
    assert len(added) == 5 and all(
        e["updated_at"] == NOW.isoformat() and e["version"] == 1 and not e["deleted"] for e in added
    )
    bumped = [e for e in data.encounters if e["id"] in before and e["version"] > before[e["id"]]["version"]]
    assert len(bumped) == 6  # six distinct records: none was both corrected and withdrawn, none bumped twice
    assert all(e["version"] == before[e["id"]]["version"] + 1 and e["updated_at"] == NOW.isoformat() for e in bumped)
    assert sum(1 for e in bumped if e["deleted"]) == 2


def test_new_encounters_continue_the_numbering_and_never_reuse_an_id() -> None:
    data = generate(3, 60)
    last = max(int(e["id"].rsplit("-", 1)[1]) for e in data.encounters)
    evolve(data, random.Random(1), NOW, new=3, changed=0, removed=0)
    assert sorted(int(e["id"].rsplit("-", 1)[1]) for e in data.encounters)[-3:] == [last + 1, last + 2, last + 3]


def test_evolve_with_nothing_to_do_touches_nothing_and_an_empty_registry_does_not_crash() -> None:
    data = generate(3, 30)
    assert evolve(data, random.Random(1), NOW, new=0, changed=0, removed=0) == 0
    empty = Dataset(people=[{"id": "reg-p-1", "deleted": False, "team_code": "T01"}])
    assert evolve(empty, random.Random(1), NOW, new=1, changed=5, removed=5) == 1  # one new; nothing existed to change


def test_when_there_is_less_to_change_than_asked_the_corrections_come_before_the_withdrawals() -> None:
    data = generate(3, 4)
    existing = sum(1 for e in data.encounters if not e["deleted"])
    touched = evolve(data, random.Random(1), NOW, new=0, changed=existing, removed=5)
    assert touched == existing
    assert sum(1 for e in data.encounters if e["deleted"]) == 0
