"""What the registry sends, validated at the edge.

Unknown fields are dropped here (`extra="ignore"`): a registry that starts sending a phone number does not get it
stored by accident. Anything that does not fit is rejected and counted, never half-applied.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EncounterKind = Literal["consultation", "checkup", "screening", "home-visit", "vaccination"]
TeamKind = Literal["primary-care", "specialist", "mobile"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=0)
    updated_at: AwareDatetime


class RegistryTeam(_Record):
    code: str = Field(min_length=1, max_length=32)  # the business key: the registry lists some teams twice
    name: str = Field(min_length=1, max_length=120)
    kind: TeamKind
    active: bool


class RegistryPerson(_Record):
    national_id: str
    name: str
    birth_date: date
    chronic: bool
    team_code: str | None = None
    registered_on: date
    refreshed_on: date
    deleted: bool = False


class RegistryEncounter(_Record):
    person_id: str = Field(min_length=1, max_length=64)
    team_code: str | None = None
    kind: EncounterKind
    occurred_on: date
    deleted: bool = False


ENTITY_MODELS: dict[str, type[_Record]] = {
    "teams": RegistryTeam,
    "people": RegistryPerson,
    "encounters": RegistryEncounter,
}
ENTITIES = tuple(ENTITY_MODELS)  # the order matters: teams, then people, then encounters


class Page(BaseModel):
    """Raw records, oldest first, and whether the registry has more after the last one."""

    items: list[dict[str, object]]
    has_more: bool = False
