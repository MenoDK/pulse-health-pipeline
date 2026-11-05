"""What the registry may send: validated at the edge, unknown fields dropped, nothing half-accepted."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pulse.records import ENTITIES, ENTITY_MODELS, Page, RegistryEncounter, RegistryPerson, RegistryTeam

STAMP = "2026-06-01T10:00:00+00:00"

ENCOUNTER = {
    "id": "reg-e-1",
    "person_id": "reg-p-1",
    "team_code": "T01",
    "kind": "consultation",
    "occurred_on": "2026-05-01",
    "version": 1,
    "deleted": False,
    "updated_at": STAMP,
}
PERSON = {
    "id": "reg-p-1",
    "national_id": "12345678909",
    "name": "Ana Souza",
    "birth_date": "1980-02-03",
    "chronic": True,
    "team_code": "T01",
    "registered_on": "2000-01-01",
    "refreshed_on": "2025-01-01",
    "version": 2,
    "updated_at": STAMP,
}
TEAM = {
    "id": "reg-t-1",
    "code": "T01",
    "name": "Team One",
    "kind": "mobile",
    "active": True,
    "version": 1,
    "updated_at": STAMP,
}


def test_a_complete_record_of_each_kind_is_accepted() -> None:
    assert RegistryEncounter.model_validate(ENCOUNTER).kind == "consultation"
    assert RegistryPerson.model_validate(PERSON).deleted is False  # the default
    assert RegistryTeam.model_validate(TEAM).code == "T01"


def test_fields_the_pipeline_did_not_ask_for_are_dropped_not_stored() -> None:
    record = RegistryPerson.model_validate(
        {**PERSON, "phone": "+00 000 0000", "email": "x@example.test", "address": "1 Nowhere St"}
    )
    dumped = record.model_dump()
    assert not {"phone", "email", "address"} & set(dumped)


@pytest.mark.parametrize(
    ("model", "base", "change"),
    [
        (RegistryEncounter, ENCOUNTER, {"kind": "surgery"}),
        (RegistryEncounter, ENCOUNTER, {"updated_at": "2026-06-01T10:00:00"}),  # no offset: which instant is it?
        (RegistryEncounter, ENCOUNTER, {"occurred_on": "not a date"}),
        (RegistryEncounter, ENCOUNTER, {"person_id": ""}),
        (RegistryEncounter, ENCOUNTER, {"version": -1}),
        (RegistryEncounter, ENCOUNTER, {"id": "x" * 65}),
        (RegistryTeam, TEAM, {"kind": "flying"}),
        (RegistryTeam, TEAM, {"code": ""}),
        (RegistryTeam, TEAM, {"name": "n" * 121}),
        (RegistryPerson, PERSON, {"birth_date": "yesterday"}),
        (RegistryPerson, PERSON, {"chronic": "maybe"}),
    ],
)
def test_a_record_that_does_not_fit_is_refused(model: type, base: dict[str, object], change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**base, **change})


@pytest.mark.parametrize("missing", ["id", "version", "updated_at", "person_id", "kind", "occurred_on"])
def test_a_record_with_a_required_field_missing_is_refused(missing: str) -> None:
    with pytest.raises(ValidationError):
        RegistryEncounter.model_validate({k: v for k, v in ENCOUNTER.items() if k != missing})


def test_a_record_cannot_be_changed_after_validation() -> None:
    record = RegistryEncounter.model_validate(ENCOUNTER)
    with pytest.raises(ValidationError):
        record.kind = "checkup"  # type: ignore[misc]


def test_entities_are_synchronised_teams_then_people_then_encounters_and_each_has_a_model() -> None:
    assert ENTITIES == ("teams", "people", "encounters")
    assert set(ENTITY_MODELS) == set(ENTITIES)


def test_a_page_defaults_to_the_last_one_and_needs_a_list_of_objects() -> None:
    assert Page(items=[]).has_more is False
    with pytest.raises(ValidationError):
        Page.model_validate({"items": "nope"})
    with pytest.raises(ValidationError):
        Page.model_validate({"items": ["not an object"]})
