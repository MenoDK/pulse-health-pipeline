"""A seeded generator of fictitious registry data.

Nothing here is real, and nothing is derived from real data. The names are made of syllables, the national
identifiers are random digits with valid check digits, and the proportions are chosen so that the indicators land in
different bands instead of all passing. The same seed always gives the same dataset.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pulse.identifiers import with_check_digits

_SYLLABLES = ["al", "bra", "cel", "dor", "el", "fra", "gui", "hel", "iv", "jo", "kal", "lu", "mar", "nel", "or", "pen"]
_TEAM_KINDS = ["primary-care", "primary-care", "primary-care", "specialist", "mobile"]


@dataclass
class Dataset:
    teams: list[dict[str, Any]] = field(default_factory=list)
    people: list[dict[str, Any]] = field(default_factory=list)
    encounters: list[dict[str, Any]] = field(default_factory=list)
    as_of: date = date(2026, 6, 30)

    def entity(self, name: str) -> list[dict[str, Any]]:
        return {"teams": self.teams, "people": self.people, "encounters": self.encounters}[name]


def _name(rng: random.Random) -> str:
    def word() -> str:
        return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(2, 3))).capitalize()

    return f"{word()} {word()}"


def _months_ago(as_of: date, months: int, rng: random.Random) -> date:
    return as_of - timedelta(days=int(months * 30.4) + rng.randint(0, 20))


def _stamp(as_of: date, rng: random.Random, spread_days: int = 200) -> datetime:
    base = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC)
    return base - timedelta(days=rng.randint(0, spread_days), seconds=rng.randint(0, 86_399))


def generate(seed: int = 7, subjects: int = 600, as_of: date = date(2026, 6, 30)) -> Dataset:
    """A registry with a few teams (some listed twice), `subjects` people and their encounters."""
    rng = random.Random(seed)
    data = Dataset(as_of=as_of)

    codes = [f"T{n:02d}" for n in range(1, 9)]
    for n, code in enumerate(codes, start=1):
        data.teams.append(_team(f"reg-t-{n:02d}", code, rng, as_of, version=1))
    # The registry lists three teams a second time under another id, as real registries do.
    for n, code in enumerate(codes[:3], start=len(codes) + 1):
        data.teams.append(_team(f"reg-t-{n:02d}", code, rng, as_of, version=1))

    encounter_no = 0

    def add_encounter(person: dict[str, Any], kind: str, when: date) -> None:
        nonlocal encounter_no
        encounter_no += 1
        data.encounters.append(
            {
                "id": f"reg-e-{encounter_no:07d}",
                "person_id": person["id"],
                "team_code": person["team_code"],
                "kind": kind,
                "occurred_on": when.isoformat(),
                "version": 1,
                "deleted": False,
                "updated_at": _stamp(as_of, rng).isoformat(),
            }
        )

    for n in range(1, subjects + 1):
        band = rng.random()
        if band < 0.07:
            age_months = rng.randint(1, 23)
        elif band < 0.20:
            age_months = rng.randint(24, 24 * 24)
        elif band < 0.78:
            age_months = rng.randint(24 * 25, 12 * 64)
        else:
            age_months = rng.randint(12 * 65, 12 * 92)
        birth = as_of - timedelta(days=int(age_months * 30.44))
        adult = 25 * 12 <= age_months < 65 * 12
        chronic = age_months >= 30 * 12 and rng.random() < 0.28
        refreshed = _months_ago(as_of, rng.choice([2, 5, 9, 14, 20, 30, 40]) if rng.random() < 0.9 else 3, rng)
        person = {
            "id": f"reg-p-{n:06d}",
            "national_id": _national_id(rng),
            "name": _name(rng),
            "birth_date": birth.isoformat(),
            "chronic": chronic,
            "team_code": rng.choice(codes),
            "registered_on": min(birth + timedelta(days=rng.randint(30, 4000)), as_of).isoformat(),
            "refreshed_on": min(refreshed, as_of).isoformat(),
            "version": 1,
            "deleted": False,
            "updated_at": _stamp(as_of, rng).isoformat(),
        }
        data.people.append(person)

        if age_months < 24:
            for _ in range(rng.choices([0, 1, 2, 3, 4], weights=[10, 15, 25, 35, 15])[0]):
                add_encounter(person, "checkup", _months_ago(as_of, rng.randint(0, age_months), rng))
        if chronic and rng.random() < 0.72:
            add_encounter(person, "consultation", _months_ago(as_of, rng.randint(0, 11), rng))
        if adult and rng.random() < 0.55:
            add_encounter(person, "screening", _months_ago(as_of, rng.randint(0, 35), rng))
        if age_months >= 65 * 12 and rng.random() < 0.5:
            add_encounter(person, "home-visit", _months_ago(as_of, rng.randint(0, 11), rng))
        for _ in range(rng.choices([0, 1, 2], weights=[50, 35, 15])[0]):
            add_encounter(
                person, rng.choice(["consultation", "vaccination"]), _months_ago(as_of, rng.randint(0, 30), rng)
            )

    # One person in a hundred arrives with an identifier whose check digits are wrong.
    for flawed in data.people[::100]:
        flawed["national_id"] = flawed["national_id"][:-1] + str((int(flawed["national_id"][-1]) + 1) % 10)
    return data


def _national_id(rng: random.Random) -> str:
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        if len(set(base)) > 1:
            return with_check_digits(base)


def _team(registry_id: str, code: str, rng: random.Random, as_of: date, *, version: int) -> dict[str, Any]:
    return {
        "id": registry_id,
        "code": code,
        "name": f"Team {_name(rng)}",
        "kind": rng.choice(_TEAM_KINDS),
        "active": True,
        "version": version,
        "updated_at": _stamp(as_of, rng).isoformat(),
    }


def evolve(
    data: Dataset, rng: random.Random, now: datetime, *, new: int = 20, changed: int = 10, removed: int = 3
) -> int:
    """Change the registry the way a week of work would: new encounters, corrected ones, withdrawn ones.

    The corrected and the withdrawn are drawn together from encounters that already existed, so no record is both, and
    a record created now is not changed in the same breath. Every touched record is stamped `updated_at = now`, a
    changed or withdrawn one with a higher version. Returns how many distinct records were touched.
    """
    touched = 0
    last = max(int(e["id"].rsplit("-", 1)[1]) for e in data.encounters) if data.encounters else 0
    people = [p for p in data.people if not p["deleted"]]
    existing = [e for e in data.encounters if not e["deleted"]]
    chosen = rng.sample(existing, min(changed + removed, len(existing)))  # changed first when there are not enough
    for n in range(1, new + 1):
        person = rng.choice(people)
        data.encounters.append(
            {
                "id": f"reg-e-{last + n:07d}",
                "person_id": person["id"],
                "team_code": person["team_code"],
                "kind": rng.choice(["consultation", "checkup", "screening", "home-visit"]),
                "occurred_on": (now.date() - timedelta(days=rng.randint(0, 6))).isoformat(),
                "version": 1,
                "deleted": False,
                "updated_at": now.isoformat(),
            }
        )
        touched += 1
    for record in chosen[:changed]:
        record["version"] += 1
        record["kind"] = rng.choice(["consultation", "checkup", "screening", "home-visit"])
        record["updated_at"] = now.isoformat()
        touched += 1
    for record in chosen[changed:]:
        record["version"] += 1
        record["deleted"] = True
        record["updated_at"] = now.isoformat()
        touched += 1
    return touched
