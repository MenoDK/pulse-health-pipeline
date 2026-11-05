"""Retry delays: exponential, capped, with jitter that is deterministic for a message.

Plain exponential backoff makes every message that failed together retry together. Spreading each delay over
[raw/2, raw] breaks that up. Seeding the spread with the message key and the attempt makes it reproducible, so a test
can pin it and an operator reading a log can see why two messages retried at different moments.
"""

from __future__ import annotations

import random


def backoff_seconds(attempt: int, key: str, *, base: int, cap: int) -> int:
    """Seconds to wait after `attempt` failed attempts (1 = the first failure)."""
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    if base < 1 or cap < 1:
        raise ValueError("base and cap must be positive")
    raw = min(cap, base * (1 << min(attempt - 1, 40)))
    half = raw // 2
    spread = half + random.Random(f"{key}:{attempt}").randint(0, raw - half)  # noqa: S311  (spread, not a secret)
    return max(1, spread)  # a raw delay of one second can spread down to zero: never retry at once
