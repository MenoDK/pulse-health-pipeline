"""Engine and small helpers shared by the services."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, Engine, create_engine, text

from pulse.clock import Clock, OffsetClock, SystemClock
from pulse.config import Settings

LAB_CLOCK_KEY = "clock_offset_seconds"
LAB_AUTOPILOT_KEY = "autopilot"
LAB_NARRATOR_KEY = "narrator"


def make_engine(settings: Settings, *, pool_size: int = 5) -> Engine:
    return create_engine(settings.sqlalchemy_url, pool_size=pool_size, max_overflow=5, pool_pre_ping=True, future=True)


def lab_get(conn: Connection, key: str, default: Any) -> Any:
    row = conn.execute(text("SELECT value FROM lab_state WHERE key = :k"), {"k": key}).first()
    return default if row is None else row[0]


def lab_set(conn: Connection, key: str, value: Any) -> None:
    conn.execute(
        text(
            "INSERT INTO lab_state (key, value) VALUES (:k, CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
        ),
        {"k": key, "v": json.dumps(value)},
    )


def make_clock(settings: Settings, engine: Engine) -> Clock:
    """The system clock, or in lab mode the system clock plus an offset kept in the database."""
    if not settings.lab_mode:
        return SystemClock()

    def read() -> int:
        with engine.connect() as conn:
            return int(lab_get(conn, LAB_CLOCK_KEY, 0))

    return OffsetClock(read)


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()
