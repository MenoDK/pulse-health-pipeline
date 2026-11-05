"""Narrators that misbehave, for the lab only.

They exist to show the check in `narrative.py` doing its job: each one produces fluent text with one defect that a
reader skimming the page would not notice. The API only offers them when the lab is on.
"""

from __future__ import annotations

import re
from typing import Any

from pulse.indicators.narrative import Narrator, TemplateNarrator


class InventingNarrator:
    """Adds a forecast that appears nowhere in the data."""

    def narrate(self, report: dict[str, Any]) -> str:
        return TemplateNarrator().narrate(report) + " Analysts expect a 12.5% improvement by next quarter."


class RoundingNarrator:
    """Rounds the first percentage to a whole number, which reads better and is not what the report says."""

    def narrate(self, report: dict[str, Any]) -> str:
        text = TemplateNarrator().narrate(report)
        return re.sub(r"(\d+)\.(\d)%", lambda m: f"{m.group(1)}%", text, count=1)


class LeakingNarrator:
    """Helpfully names a person."""

    def narrate(self, report: dict[str, Any]) -> str:
        return TemplateNarrator().narrate(report) + " The record that moved most is pk1.mfrggzdfmztwq2lknnwg23tpoi."


NARRATORS: dict[str, Narrator] = {
    "template": TemplateNarrator(),
    "invents": InventingNarrator(),
    "rounds": RoundingNarrator(),
    "leaks": LeakingNarrator(),
}
