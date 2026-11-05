#!/usr/bin/env python3
"""Mutation check by hand: break one decision at a time and require the matching tests to go red.

A test that has never been seen failing is decoration. Each mutant below deletes or inverts one decision the
pipeline makes (a guard, a comparison, a lock, a column of SQL); the named test modules must then fail. The script
restores every file byte-for-byte, proves it did, and exits non-zero if any mutant survives.

It needs the same services the integration tests need (`make mutate` starts them): DATABASE_URL, and REDIS_URL for the
few tests that talk to the broker.

    python scripts/sabotage.py            # all mutants
    python scripts/sabotage.py -k queue   # only those whose name contains "queue"
    python scripts/sabotage.py --check    # only prove that every pattern occurs exactly once (no tests run)

The source is rewritten in place while this runs: do not build a Docker image from the working tree meanwhile.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "pulse"
TIMEOUT_SECONDS = 240


@dataclass(frozen=True)
class Mutant:
    name: str
    file: str  # relative to src/pulse
    old: str
    new: str
    tests: str  # test modules (space separated) that must fail

    @property
    def path(self) -> Path:
        return SRC / self.file


def m(name: str, file: str, old: str, new: str, tests: str) -> Mutant:
    return Mutant(name, file, old, new, tests)


MUTANTS: tuple[Mutant, ...] = (
    # --- synchronisation -------------------------------------------------------------------------------------------
    m(
        "sync: the stored position can move backwards",
        "sync.py",
        '"   OR excluded.cursor_updated_at > sync_state.cursor_updated_at"',
        '"   OR true"',
        "tests/test_sync.py",
    ),
    m(
        "sync: no overlap window before the stored position",
        "sync.py",
        "after_at = None if stored is None else stored - self._overlap",
        "after_at = None if stored is None else stored",
        "tests/test_sync.py",
    ),
    m("sync: two runs may overlap", "sync.py", "if not got:", "if False:", "tests/test_sync.py"),
    m(
        "sync: the position is never stored",
        "sync.py",
        "self._advance(conn, entity, position[0])",
        "pass",
        "tests/test_sync.py",
    ),
    m(
        "sync: out-of-order pages are trusted",
        "sync.py",
        "if previous is not None and current < previous:",
        "if False:",
        "tests/test_sync.py",
    ),
    m(
        "sync: a failed run may quote the record that broke it",
        "sync.py",
        'return type(exc).__name__ + (f" (SQLSTATE {sqlstate})" if isinstance(sqlstate, str) else "")',
        'return f"{type(exc).__name__}: {exc}"[:300]',
        "tests/test_sync.py",
    ),
    m(
        "sync: an identifier that fails its checksum is stored",
        "sync.py",
        "if not is_valid_national_id(p.national_id):",
        "if False:",
        "tests/test_sync.py",
    ),
    m(
        "sync: an invalid record aborts the whole run",
        "sync.py",
        "except ValidationError:",
        "except ZeroDivisionError:",
        "tests/test_sync.py",
    ),
    m(
        "sync: a written encounter queues no message",
        "sync.py",
        "queued = enqueue_many(conn, messages, now)",
        "queued = 0",
        "tests/test_sync.py",
    ),
    m(
        "sync: records that were not written are not counted as stale",
        "sync.py",
        "stale = len(items) - rejected - applied",
        "stale = 0",
        "tests/test_sync.py",
    ),
    m(
        "sync: inside a page the oldest copy of a record wins",
        "sync.py",
        '(row["version"], row["source_updated_at"]) > (',
        '(row["version"], row["source_updated_at"]) < (',
        "tests/test_sync.py",
    ),
    m(
        "sync: a replayed page is written again",
        "sync.py",
        "> tuple_(table.c.version, table.c.source_updated_at)",
        ">= tuple_(table.c.version, table.c.source_updated_at)",
        "tests/test_sync.py",
    ),
    m(
        "sync: a later timestamp beats a higher version",
        "sync.py",
        "return tuple_(excluded.version, excluded.source_updated_at) > tuple_(table.c.version, table.c.source_updated_at)",
        "return excluded.source_updated_at > table.c.source_updated_at",
        "tests/test_sync.py",
    ),
    m(
        "sync: a person is stored under the registry's own id",
        "sync.py",
        '"subject_key": self._pseudonyms.subject_key(p.id),',
        '"subject_key": p.id,',
        "tests/test_sync.py tests/test_privacy.py",
    ),
    m(
        "sync: an encounter points at the registry's own person id",
        "sync.py",
        '"subject_key": self._pseudonyms.subject_key(e.person_id),',
        '"subject_key": e.person_id,',
        "tests/test_sync.py tests/test_privacy.py",
    ),
    # --- the registry client and the records it sends --------------------------------------------------------------
    m(
        "registry: a refusal is retried as if it were an outage",
        "registry.py",
        "if response.status_code < 500:",
        "if False:",
        "tests/test_registry_client.py",
    ),
    m(
        "registry: an outage is not retried",
        "registry.py",
        "for attempt in range(self._retries + 1):",
        "for attempt in range(1):",
        "tests/test_registry_client.py",
    ),
    m(
        "registry: a malformed page error quotes the page",
        "registry.py",
        'raise RegistryError("the registry answered something that is not a page") from None',
        'raise RegistryError(f"not a page: {response.text[:200]}") from None',
        "tests/test_registry_client.py tests/test_privacy.py tests/test_sync.py",
    ),
    m(
        "registry: the tie-breaking id is not sent",
        "registry.py",
        'params["after_id"] = after_id',
        "pass",
        "tests/test_registry_client.py",
    ),
    m(
        "records: fields nobody asked for are kept",
        "records.py",
        'extra="ignore", frozen=True',
        'extra="allow", frozen=True',
        "tests/test_records.py tests/test_privacy.py",
    ),
    # --- the transmission queue ------------------------------------------------------------------------------------
    m(
        "queue: a claim waits for messages another worker holds",
        "exchange/queue.py",
        'LIMIT :limit FOR UPDATE SKIP LOCKED"',
        'LIMIT :limit FOR UPDATE"',
        "tests/test_queue.py",
    ),
    m(
        "queue: the attempt is not counted at claim time",
        "exchange/queue.py",
        "attempts = o.attempts + 1",
        "attempts = o.attempts",
        "tests/test_queue.py",
    ),
    m(
        "queue: messages of a dead worker are never taken over",
        "exchange/queue.py",
        "EXPIRED = (\"status = 'sending' AND lease_until < :now\"",
        "EXPIRED = (\"status = 'sending' AND lease_until > :now\"",
        "tests/test_queue.py",
    ),
    m(
        "queue: messages that are not due yet are claimed",
        "exchange/queue.py",
        "PENDING = (\"status = 'pending' AND not_before <= :now\"",
        "PENDING = (\"status = 'pending'\"",
        "tests/test_queue.py",
    ),
    m(
        "queue: a claim may take more than the batch",
        "exchange/queue.py",
        "room = limit - len(taken)",
        "room = limit",
        "tests/test_queue.py",
    ),
    m(
        "queue: expired messages are read in id order, not lease order (no index)",
        "exchange/queue.py",
        '"lease_until, id")',
        '"id")',
        "tests/test_schema.py",
    ),
    m(
        "queue: pending messages are read in id order, not due order (no index)",
        "exchange/queue.py",
        '"not_before, id")',
        '"id")',
        "tests/test_schema.py",
    ),
    m(
        "queue: a worker whose lease was taken over can overwrite the result",
        "exchange/queue.py",
        "\"WHERE id = :id AND status = 'sending' AND locked_by = :worker\"",
        "\"WHERE id = :id AND status = 'sending' AND :worker IS NOT NULL\"",
        "tests/test_queue.py",
    ),
    m(
        "queue: a message on its last attempt is never given up on",
        "exchange/queue.py",
        "\"WHERE status = 'sending' AND lease_until < :now AND attempts >= :max\"",
        "\"WHERE status = 'sending' AND lease_until < :now AND attempts > :max\"",
        "tests/test_queue.py",
    ),
    m(
        "queue: requeueing dead messages keeps their spent attempts",
        "exchange/queue.py",
        "\"UPDATE outbox SET status = 'pending', attempts = 0, not_before = :now, lease_until = NULL, \"",
        "\"UPDATE outbox SET status = 'pending', attempts = attempts, not_before = :now, lease_until = NULL, \"",
        "tests/test_queue.py",
    ),
    m(
        "queue: the same key is queued again with a new payload",
        "exchange/queue.py",
        '"ON CONFLICT (idempotency_key) DO NOTHING"',
        '"ON CONFLICT (idempotency_key) DO UPDATE SET payload = excluded.payload"',
        "tests/test_queue.py tests/test_sync.py",
    ),
    m(
        "queue: a duplicate answer is not a success",
        "exchange/queue.py",
        'if outcome in ("delivered", "duplicate"):',
        'if outcome == "delivered":',
        "tests/test_queue.py tests/test_worker.py",
    ),
    m(
        "queue: a successful message keeps its last error",
        "exchange/queue.py",
        '"error": None if new_status == "done" else detail[:300],',
        '"error": detail[:300],',
        "tests/test_queue.py tests/test_worker.py",
    ),
    m(
        "queue: a taken-over message is not marked as taken over",
        "exchange/queue.py",
        "r.attempts, r.id in took_over)",
        "r.attempts, False)",
        "tests/test_queue.py tests/test_worker.py",
    ),
    m(
        "queue: every claimed message is marked as taken over",
        "exchange/queue.py",
        "r.attempts, r.id in took_over)",
        "r.attempts, r.attempts > 1)",
        "tests/test_queue.py tests/test_worker.py",
    ),
    # --- the worker that drains it ---------------------------------------------------------------------------------
    m(
        "worker: the report does not say how many came from a dead worker",
        "exchange/worker.py",
        "report.taken_over = sum(1 for m in messages if m.taken_over)",
        "report.taken_over = 0",
        "tests/test_worker.py",
    ),
    m(
        "worker: an outage is not noticed, every message waits for its own timeout",
        "exchange/worker.py",
        "if failures >= stop_after_failures and index + 1 < len(messages):",
        "if False:",
        "tests/test_worker.py",
    ),
    m(
        "worker: transport failures need not be consecutive",
        "exchange/worker.py",
        'failures = failures + 1 if delivery.outcome == "retry" and delivery.http_status is None else 0',
        'failures = failures + 1 if delivery.outcome == "retry" and delivery.http_status is None else failures',
        "tests/test_worker.py",
    ),
    m(
        "worker: an answer from the gateway counts as an outage",
        "exchange/worker.py",
        'delivery.outcome == "retry" and delivery.http_status is None',
        'delivery.outcome == "retry"',
        "tests/test_worker.py",
    ),
    m(
        "worker: sends after the lease is about to expire",
        "exchange/worker.py",
        "if clock.now() >= deadline:",
        "if False:",
        "tests/test_worker.py",
    ),
    m(
        "worker: released messages keep the attempt the claim spent",
        "exchange/worker.py",
        "\"UPDATE outbox SET status = 'pending', attempts = attempts - 1, lease_until = NULL, locked_by = NULL \"",
        "\"UPDATE outbox SET status = 'pending', attempts = attempts, lease_until = NULL, locked_by = NULL \"",
        "tests/test_worker.py",
    ),
    m(
        "worker: a message is retried for ever",
        "exchange/worker.py",
        "if message.attempts >= max_attempts:",
        "if False:",
        "tests/test_worker.py",
    ),
    m(
        "worker: the gateway's Retry-After is ignored",
        "exchange/worker.py",
        "delivery.retry_after or 0,",
        "0,",
        "tests/test_worker.py",
    ),
    m(
        "worker: a discarded result is counted as a success",
        "exchange/worker.py",
        "if not won:",
        "if False:",
        "tests/test_worker.py",
    ),
    m(
        "worker: exhausted messages are never reaped",
        "exchange/worker.py",
        "report.reaped = reap_exhausted(engine, clock.now(), max_attempts)",
        "report.reaped = 0",
        "tests/test_worker.py",
    ),
    # --- backoff ---------------------------------------------------------------------------------------------------
    m(
        "backoff: the jitter is different on every run",
        "exchange/backoff.py",
        'random.Random(f"{key}:{attempt}")',
        "random.Random()",
        "tests/test_backoff.py",
    ),
    m(
        "backoff: a delay can be zero",
        "exchange/backoff.py",
        "return max(1, spread)",
        "return spread",
        "tests/test_backoff.py",
    ),
    m(
        "backoff: the delay has no ceiling",
        "exchange/backoff.py",
        "raw = min(cap, base * (1 << min(attempt - 1, 40)))",
        "raw = base * (1 << min(attempt - 1, 40))",
        "tests/test_backoff.py",
    ),
    m("backoff: no jitter at all", "exchange/backoff.py", "half = raw // 2", "half = raw", "tests/test_backoff.py"),
    # --- the connector ---------------------------------------------------------------------------------------------
    m(
        "gateway: a server error is final",
        "exchange/gateway.py",
        " or status >= 500 or 300 <= status < 400:",
        " or status >= 600 or 300 <= status < 400:",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: a redirect is final",
        "exchange/gateway.py",
        " or status >= 500 or 300 <= status < 400:",
        " or status >= 500:",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: a refused payload is retried for ever",
        "exchange/gateway.py",
        'return Delivery("dead", status, f"the gateway refuses this payload ({status})")',
        'return Delivery("retry", status, f"the gateway refuses this payload ({status})")',
        "tests/test_gateway.py",
    ),
    m(
        "gateway: a duplicate answer is a conflict",
        "exchange/gateway.py",
        'if isinstance(body, dict) and body.get("error") == "duplicate":',
        "if False:",
        "tests/test_gateway.py tests/test_standin_gateway.py",
    ),
    m(
        "gateway: an expired token is not renewed once",
        "exchange/gateway.py",
        "if response.status_code == 401 and not reauthenticated:",
        "if False:",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: a slow thread throws away a fresh token",
        "exchange/gateway.py",
        "if self._token is not None and self._token.value == value:",
        "if self._token is not None:",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: a token is used until the very second it expires",
        "exchange/gateway.py",
        "self._clock.now() >= token.expires_at - self._margin",
        "self._clock.now() >= token.expires_at",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: many threads fetch many tokens",
        "exchange/gateway.py",
        "self._lock = threading.Lock()",
        'self._lock = type("NoLock", (), {"__enter__": lambda self: None, "__exit__": lambda self, *a: None})()',
        "tests/test_gateway.py",
    ),
    m(
        "gateway: an answer that is not a token is used as one",
        "exchange/gateway.py",
        "if not isinstance(value, str) or not value or lifetime <= 0:",
        "if False:",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: a token endpoint answering garbage crashes the send",
        "exchange/gateway.py",
        "except (ValueError, KeyError, TypeError, AttributeError) as exc:",
        "except ZeroDivisionError as exc:",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: a token endpoint refusing us is read as a token",
        "exchange/gateway.py",
        "if response.status_code != 200:",
        "if False:",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: the idempotency key is not sent",
        "exchange/gateway.py",
        ', "Idempotency-Key": key}',
        "}",
        "tests/test_gateway.py tests/test_standin_gateway.py",
    ),
    m(
        "gateway: a Retry-After of a year is obeyed",
        "exchange/gateway.py",
        "raw.isdigit() and int(raw) <= 86_400",
        "raw.isdigit()",
        "tests/test_gateway.py",
    ),
    m(
        "gateway: the client certificate is not presented",
        "exchange/gateway.py",
        "context.load_cert_chain(cert_file, key_file or None)",
        "pass",
        "tests/test_mtls.py",
    ),
    # --- indicators ------------------------------------------------------------------------------------------------
    m(
        "indicators: withdrawn people are counted",
        "indicators/queries.py",
        "WHERE NOT deleted AND birth_month <= CAST(:as_of AS date)",
        "WHERE birth_month <= CAST(:as_of AS date)",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: withdrawn encounters are counted",
        "indicators/queries.py",
        "WHERE NOT deleted AND occurred_on <= CAST(:as_of AS date)",
        "WHERE occurred_on <= CAST(:as_of AS date)",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: encounters after the report date are counted",
        "indicators/queries.py",
        "WHERE NOT deleted AND occurred_on <= CAST(:as_of AS date)",
        "WHERE NOT deleted",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: the age in months ignores the month",
        "indicators/queries.py",
        "- (EXTRACT(YEAR FROM birth_month) * 12 + EXTRACT(MONTH FROM birth_month)) AS age_months",
        "- (EXTRACT(YEAR FROM birth_month) * 12) AS age_months",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: the chronic follow-up counts everyone",
        "indicators/queries.py",
        'FROM s WHERE s.chronic""",',
        'FROM s""",',
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: any kind of encounter is a follow-up",
        "indicators/queries.py",
        "e.kind = 'consultation'",
        "e.kind IS NOT NULL",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: the 12-month window includes its first day (follow-up)",
        "indicators/queries.py",
        "AND e.occurred_on > CAST(:as_of AS date) - interval '12 months')) AS num\n        FROM s WHERE s.chronic",
        "AND e.occurred_on >= CAST(:as_of AS date) - interval '12 months')) AS num\n        FROM s WHERE s.chronic",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: the 12-month window includes its first day (home visits)",
        "indicators/queries.py",
        "AND e.occurred_on > CAST(:as_of AS date) - interval '12 months')) AS num\n        FROM s WHERE s.age_months >= 780",
        "AND e.occurred_on >= CAST(:as_of AS date) - interval '12 months')) AS num\n        FROM s WHERE s.age_months >= 780",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: the 36-month window includes its first day",
        "indicators/queries.py",
        "e.occurred_on > CAST(:as_of AS date) - interval '36 months'",
        "e.occurred_on >= CAST(:as_of AS date) - interval '36 months'",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: the 24-month window includes its first day (registration)",
        "indicators/queries.py",
        "s.registry_refreshed_on > CAST(:as_of AS date) - interval '24 months'",
        "s.registry_refreshed_on >= CAST(:as_of AS date) - interval '24 months'",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: two check-ups are enough",
        "indicators/queries.py",
        "interval '24 months') >= 3) AS num",
        "interval '24 months') >= 2) AS num",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: a child is under 24 months, inclusive",
        "indicators/queries.py",
        'FROM s WHERE s.age_months < 24""",',
        'FROM s WHERE s.age_months <= 24""",',
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: adults up to and including 65",
        "indicators/queries.py",
        "WHERE s.age_months >= 300 AND s.age_months < 780",
        "WHERE s.age_months >= 300 AND s.age_months <= 780",
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: older people start after 65",
        "indicators/queries.py",
        'FROM s WHERE s.age_months >= 780""",',
        'FROM s WHERE s.age_months > 780""",',
        "tests/test_indicators_sql.py",
    ),
    m(
        "indicators: the five counts are read from five different moments",
        "indicators/report.py",
        '.execution_options(isolation_level="REPEATABLE READ")',
        "",
        "tests/test_indicators_sql.py",
    ),
    # --- scoring ---------------------------------------------------------------------------------------------------
    m(
        "scoring: a numerator of zero is read as no data",
        "indicators/scoring.py",
        "if denominator == 0:\n        return Band.NO_DATA",
        "if denominator == 0 or numerator == 0:\n        return Band.NO_DATA",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: counts that cannot be right are accepted",
        "indicators/scoring.py",
        "if numerator < 0 or denominator < 0 or numerator > denominator:",
        "if numerator < 0 or denominator < 0:",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: a target outside (0, 1] is accepted",
        "indicators/scoring.py",
        "if target <= 0 or target > 1:",
        "if False:",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: the target itself is not enough",
        "indicators/scoring.py",
        "if ratio >= target:",
        "if ratio > target:",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: 90% of the target is not enough for good",
        "indicators/scoring.py",
        "if ratio * 10 >= target * 9:",
        "if ratio * 10 > target * 9:",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: 70% of the target is not enough for fair",
        "indicators/scoring.py",
        "if ratio * 10 >= target * 7:",
        "if ratio * 10 > target * 7:",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: indicators without data weigh on the score",
        "indicators/scoring.py",
        "4 * sum(r.weight for r in scored)",
        "4 * sum(r.weight for r in results)",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: an indicator without data counts as zero",
        "indicators/scoring.py",
        "scored = [r for r in results if r.band != Band.NO_DATA]",
        "scored = list(results)",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: 8 is not excellent",
        "indicators/scoring.py",
        "if score >= 8:",
        "if score > 8:",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: 6.5 is not good",
        "indicators/scoring.py",
        "if score >= Fraction(13, 2):",
        "if score > Fraction(13, 2):",
        "tests/test_scoring.py",
    ),
    m("scoring: 5 is not fair", "indicators/scoring.py", "if score >= 5:", "if score > 5:", "tests/test_scoring.py"),
    m(
        "scoring: rounding truncates",
        "indicators/scoring.py",
        "(2 * magnitude.numerator * scale + magnitude.denominator) // (2 * magnitude.denominator)",
        "(2 * magnitude.numerator * scale) // (2 * magnitude.denominator)",
        "tests/test_scoring.py",
    ),
    m(
        "scoring: a negative that rounds to zero keeps its sign",
        "indicators/scoring.py",
        'return f"-{text}" if negative and scaled else text',
        'return f"-{text}" if negative else text',
        "tests/test_scoring.py",
    ),
    # --- the narrator check ----------------------------------------------------------------------------------------
    m(
        "narrator: a number that is not in the report passes",
        "indicators/narrative.py",
        "elif not is_percent and number not in allowed.plain:",
        "elif False:",
        "tests/test_narrative.py",
    ),
    m(
        "narrator: a percentage may be any count",
        "indicators/narrative.py",
        "if is_percent and number not in allowed.percent:",
        "if is_percent and number not in allowed.percent | allowed.plain:",
        "tests/test_narrative.py",
    ),
    m(
        "narrator: a stored pseudonym may be repeated in prose",
        "indicators/narrative.py",
        "if _PSEUDONYM.search(text):",
        "if False:",
        "tests/test_narrative.py",
    ),
    m(
        "narrator: a narrator that fails takes the endpoint down",
        "indicators/narrative.py",
        "    except Exception as exc:\n        text, problems",
        "    except ZeroDivisionError as exc:\n        text, problems",
        "tests/test_narrative.py",
    ),
    m(
        "narrator: 1,234 is read as 1.234",
        "indicators/narrative.py",
        'value = raw.replace(",", "") if _THOUSANDS.fullmatch(raw) else raw.replace(",", ".")',
        'value = raw.replace(",", ".")',
        "tests/test_narrative.py",
    ),
    m(
        "narrator: an essay passes",
        "indicators/narrative.py",
        "if len(text) > MAX_LENGTH:",
        "if False:",
        "tests/test_narrative.py",
    ),
    m(
        "narrator: empty text passes",
        "indicators/narrative.py",
        "if not text.strip():",
        "if False:",
        "tests/test_narrative.py",
    ),
    m(
        "narrator: a date written without its leading zero is refused",
        "indicators/narrative.py",
        'plain.update({part, part.lstrip("0") or "0"})',
        "plain.update({part})",
        "tests/test_narrative.py",
    ),
    m(
        "narrator: a gap quoted without its sign is refused",
        "indicators/narrative.py",
        'percent.add(str(item[key]).lstrip("-"))',
        "percent.add(str(item[key]))",
        "tests/test_narrative.py",
    ),
    # --- search ----------------------------------------------------------------------------------------------------
    m(
        "fusion: rank counts from the wrong end",
        "search/fusion.py",
        "scores[item] = scores.get(item, 0.0) + 1.0 / (k + position)",
        "scores[item] = scores.get(item, 0.0) + 1.0 / position",
        "tests/test_fusion.py",
    ),
    m(
        "fusion: a list that repeats an item votes for it twice",
        "search/fusion.py",
        "enumerate(dict.fromkeys(ranking), start=1)",
        "enumerate(ranking, start=1)",
        "tests/test_fusion.py",
    ),
    m("fusion: k below one is accepted", "search/fusion.py", "if k < 1:", "if False:", "tests/test_fusion.py"),
    m(
        "weighted: the weights are the wrong way round",
        "search/fusion.py",
        "item: vector_weight * vector.get(item, 0.0) + lexical_weight * lexical.get(item, 0.0)",
        "item: lexical_weight * vector.get(item, 0.0) + vector_weight * lexical.get(item, 0.0)",
        "tests/test_fusion.py",
    ),
    m(
        "weighted: an item found only by keywords is lost",
        "search/fusion.py",
        "for item in {*vector, *lexical}",
        "for item in {*vector}",
        "tests/test_fusion.py",
    ),
    m(
        "search: every word of a question must match",
        "search/store.py",
        'return " | ".join(terms) if terms else None',
        'return " & ".join(terms) if terms else None',
        "tests/test_search.py",
    ),
    m(
        "search: the best keyword match comes last",
        "search/store.py",
        "ORDER BY score DESC, doc_id, chunk_no LIMIT :limit",
        "ORDER BY score ASC, doc_id, chunk_no LIMIT :limit",
        "tests/test_search.py",
    ),
    m(
        "search: every note matches every keyword query",
        "search/store.py",
        "WHERE tsv @@ query ",
        "WHERE true ",
        "tests/test_search.py",
    ),
    m(
        "search: the nearest vector is not first",
        "search/store.py",
        "ORDER BY embedding <=> CAST(:v AS vector), doc_id, chunk_no LIMIT :limit",
        "ORDER BY doc_id, chunk_no LIMIT :limit",
        "tests/test_search.py",
    ),
    m("search: any k is accepted", "search/store.py", "if not 1 <= k <= 50:", "if False:", "tests/test_search.py"),
    m(
        "search: an unknown mode falls through to another",
        "search/store.py",
        "if mode not in MODES:",
        "if False:",
        "tests/test_search.py",
    ),
    m(
        "search: a chunk size that cannot advance is accepted",
        "search/store.py",
        "if size <= overlap or overlap < 0:",
        "if False:",
        "tests/test_search.py",
    ),
    m(
        "search: a word longer than a chunk is dropped",
        "search/store.py",
        "(length + len(tokens[end]) + 1 <= size or end == start)",
        "(length + len(tokens[end]) + 1 <= size)",
        "tests/test_search.py",
    ),
    m(
        "embedding: a text with nothing to embed becomes a zero vector",
        "search/embedding.py",
        "if not seen or norm == 0.0:",
        "if False:",
        "tests/test_embedding.py tests/test_search.py",
    ),
    m(
        "embedding: vectors are not unit length",
        "search/embedding.py",
        "return [x / norm for x in vector]",
        "return vector",
        "tests/test_embedding.py",
    ),
    m(
        "embedding: stop words are embedded",
        "search/embedding.py",
        "if w not in STOP_WORDS",
        "if True",
        "tests/test_embedding.py tests/test_search.py",
    ),
    m(
        "embedding: word boundaries are not part of the spelling",
        "search/embedding.py",
        'padded = f"^{word}$"',
        "padded = word",
        "tests/test_embedding.py",
    ),
    # --- privacy ---------------------------------------------------------------------------------------------------
    m(
        "privacy: the scan does not look inside JSON columns",
        "privacy.py",
        'TEXT_TYPES = ("text", "character varying", "character", "jsonb", "json")',
        'TEXT_TYPES = ("text", "character varying", "character")',
        "tests/test_privacy.py",
    ),
    m(
        "privacy: the scan only finds a column that is exactly the value",
        "privacy.py",
        "AS text) ~ :pattern",
        "AS text) = :pattern",
        "tests/test_privacy.py",
    ),
    m(
        "privacy: a value with regular-expression characters matches other things",
        "privacy.py",
        'pattern = "|".join(re.escape(v) for v in values if v)',
        'pattern = "|".join(v for v in values if v)',
        "tests/test_privacy.py",
    ),
    m(
        "identifiers: the check-digit weights are off by one",
        "identifiers.py",
        "weight = len(digits) + 1",
        "weight = len(digits)",
        "tests/test_identifiers.py",
    ),
    m(
        "identifiers: eleven equal digits are accepted",
        "identifiers.py",
        "if len(digits) != 11 or len(set(digits)) == 1:",
        "if len(digits) != 11:",
        "tests/test_identifiers.py",
    ),
    m(
        "identifiers: the pseudonym is a plain hash anyone can recompute",
        "identifiers.py",
        'digest = hmac.new(self._key, b"subject\\x00" + normalised.encode(), hashlib.sha256).digest()',
        'digest = hashlib.sha256(b"subject\\x00" + normalised.encode()).digest()',
        "tests/test_identifiers.py",
    ),
    m(
        "identifiers: the pseudonym does not say which key made it",
        "identifiers.py",
        'return f"p{self.key_id}.{token}"',
        'return f"p.{token}"',
        "tests/test_identifiers.py",
    ),
    m(
        "identifiers: a trailing space makes another person",
        "identifiers.py",
        "normalised = registry_person_id.strip()",
        "normalised = registry_person_id",
        "tests/test_identifiers.py",
    ),
    # --- health ----------------------------------------------------------------------------------------------------
    m(
        "health: any component down takes the whole service down",
        "health.py",
        'if any(c.status == "down" and c.component in CRITICAL for c in checks):',
        'if any(c.status == "down" for c in checks):',
        "tests/test_health.py",
    ),
    m(
        "health: a dead worker looks alive for half an hour",
        "health.py",
        "if age > 3 * HEARTBEAT_INTERVAL_SECONDS:",
        "if age > 30 * HEARTBEAT_INTERVAL_SECONDS:",
        "tests/test_health.py",
    ),
    m(
        "health: dead messages do not degrade the queue",
        "health.py",
        'return ("degraded", f"{dead} dead") if dead else ("ok", "nothing due")',
        'return ("ok", "nothing due")',
        "tests/test_health.py",
    ),
    m(
        "health: uptime is a fraction, not a percentage",
        "health.py",
        "round(100 * int(row.ok) / total, 2)",
        "round(int(row.ok) / total, 2)",
        "tests/test_health.py",
    ),
    # --- configuration and the doors in front of the lab -----------------------------------------------------------
    m(
        "config: only the word production switches the checks on",
        "config.py",
        "if self.app_env.strip().lower() in DEVELOPMENT_ENVS:",
        'if self.app_env.strip().lower() != "production":',
        "tests/test_config.py",
    ),
    m(
        "config: the demonstration API key is accepted in production",
        "config.py",
        "if self.api_key == DEMO_API_KEY or len(self.api_key) < 24:",
        "if False:",
        "tests/test_config.py",
    ),
    m(
        "config: the demonstration pseudonymisation key is accepted in production",
        "config.py",
        "if self.pseudonym_key == DEMO_PSEUDONYM_KEY or len(self.pseudonym_key) < 32:",
        "if False:",
        "tests/test_config.py",
    ),
    m(
        "config: the lab is accepted in production",
        "config.py",
        "        if self.lab_mode:\n            problems",
        "        if False:\n            problems",
        "tests/test_config.py",
    ),
    m(
        "config: the stand-in controls are accepted in production",
        "config.py",
        "if self.standin_control:",
        "if False:",
        "tests/test_config.py",
    ),
    m(
        "api: a foreign Host header is answered",
        "api/security.py",
        'if not host_allowed(request.headers.get("host", "")):',
        "if False:",
        "tests/test_api.py",
    ),
    m(
        "api: a change from another site is accepted",
        "api/security.py",
        "if request.method not in _SAFE_METHODS and not same_origin(request):",
        "if False:",
        "tests/test_api.py",
    ),
    m(
        "api: a browser's cross-site marker is ignored",
        "api/security.py",
        'if site is not None and site not in {"same-origin", "none"}:',
        "if False:",
        "tests/test_api.py",
    ),
    m(
        "api: an origin that is not this server's is accepted",
        "api/security.py",
        'return urlsplit(origin).netloc.lower() == request.headers.get("host", "").lower()',
        "return True",
        "tests/test_api.py",
    ),
    m(
        "api: no content security policy",
        "api/security.py",
        'response.headers["content-security-policy"] = CSP',
        "pass",
        "tests/test_api.py",
    ),
    m(
        "api: the key is not checked outside the lab",
        "api/security.py",
        "        if settings.lab_mode:\n            return  # the gates above",
        "        if True:\n            return  # the gates above",
        "tests/test_api.py",
    ),
    m(
        "api: the lab levers exist when the lab is off",
        "api/app.py",
        "    if settings.lab_mode:\n        app.include_router(build_lab_router",
        "    if True:\n        app.include_router(build_lab_router",
        "tests/test_api.py",
    ),
    # (Publishing `docs_url` alone would be an equivalent mutant: FastAPI serves no docs page without a schema URL.)
    m(
        "api: the schema and the docs are published when the lab is off",
        "api/app.py",
        'openapi_url="/api/openapi.json" if settings.lab_mode else None,',
        'openapi_url="/api/openapi.json",',
        "tests/test_api.py",
    ),
    m(
        "lab: an unknown gateway scenario reads as a dead gateway",
        "api/lab.py",
        "if body.name not in SCENARIOS:",
        "if False:",
        "tests/test_api.py",
    ),
    m(
        "lab: an unknown narrator is accepted",
        "api/lab.py",
        "if body.mode not in NARRATORS:",
        "if False:",
        "tests/test_api.py",
    ),
    m(
        "lab: the privacy proof shows a person the pipeline refused",
        "api/lab.py",
        'shown = [p for p in sample if is_valid_national_id(p["national_id"])][:3]',
        "shown = sample[:3]",
        "tests/test_api.py",
    ),
    m(
        "lab: a gateway call whose connection broke is not repeated",
        "api/lab.py",
        "            except httpx.TransportError:\n                response = services.gateway.raw(method, path, **kwargs)\n",
        "            except httpx.TransportError:\n                raise\n",
        "tests/test_api.py",
    ),
    m(
        "lab: a gateway call is repeated even when the gateway answered with an error",
        "api/lab.py",
        "                response = services.gateway.raw(method, path, **kwargs)\n"
        "            except httpx.TransportError:\n"
        "                response = services.gateway.raw(method, path, **kwargs)\n"
        "            response.raise_for_status()\n",
        "                response = services.gateway.raw(method, path, **kwargs)\n"
        "                response.raise_for_status()\n"
        "            except httpx.HTTPError:\n"
        "                response = services.gateway.raw(method, path, **kwargs)\n"
        "                response.raise_for_status()\n",
        "tests/test_api.py",
    ),
    m(
        "lab: a gateway call is repeated twice instead of once",
        "api/lab.py",
        "            except httpx.TransportError:\n                response = services.gateway.raw(method, path, **kwargs)\n",
        "            except httpx.TransportError:\n"
        "                services.gateway.raw(method, path, **kwargs)\n"
        "                response = services.gateway.raw(method, path, **kwargs)\n",
        "tests/test_api.py",
    ),
    m(
        "stand-in: the registry ignores the day it is asked to be up to date to",
        "standin/registry_app.py",
        "state = _State(seed, subjects, as_of or Dataset().as_of)",
        "state = _State(seed, subjects, Dataset().as_of)",
        "tests/test_standin_registry.py",
    ),
    m(
        "stand-in: a start-up day that is not a date is ignored",
        "standin/registry_app.py",
        "as_of=date.fromisoformat(as_of) if as_of else None,",
        "as_of=None,",
        "tests/test_standin_registry.py",
    ),
    # --- scheduling ------------------------------------------------------------------------------------------------
    m(
        "tasks: a task is acknowledged before it ran",
        "tasks.py",
        "task_acks_late=True,",
        "task_acks_late=False,",
        "tests/test_tasks.py",
    ),
    m(
        "tasks: a task whose worker died is lost",
        "tasks.py",
        "task_reject_on_worker_lost=True,",
        "task_reject_on_worker_lost=False,",
        "tests/test_tasks.py",
    ),
    m(
        "tasks: a long task can sit behind prefetched ones",
        "tasks.py",
        "worker_prefetch_multiplier=1,",
        "worker_prefetch_multiplier=4,",
        "tests/test_tasks.py",
    ),
    m(
        "tasks: the broker accepts pickled messages",
        "tasks.py",
        'accept_content=["json"],',
        'accept_content=["json", "pickle"],',
        "tests/test_tasks.py",
    ),
    m(
        "tasks: the lab's autopilot switch is ignored",
        "tasks.py",
        "return bool(lab_get(conn, LAB_AUTOPILOT_KEY, False))",
        "return True",
        "tests/test_tasks.py",
    ),
    m(
        "tasks: outside the lab the scheduled work does not run",
        "tasks.py",
        "if not services.settings.lab_mode:\n        return True",
        "if not services.settings.lab_mode:\n        return False",
        "tests/test_tasks.py",
    ),
    # --- the data generator ----------------------------------------------------------------------------------------
    m(
        "synthetic: a different registry on every start",
        "synthetic.py",
        "rng = random.Random(seed)",
        "rng = random.Random()",
        "tests/test_synthetic.py",
    ),
    m(
        "synthetic: a record can be changed and withdrawn in the same breath",
        "synthetic.py",
        "chosen = rng.sample(existing, min(changed + removed, len(existing)))",
        "chosen = rng.sample(existing, min(changed, len(existing))) + rng.sample(existing, min(removed, len(existing)))",
        "tests/test_synthetic.py",
    ),
)


def tree_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(SRC.rglob("*.py")):
        digest.update(str(path.relative_to(SRC)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_tests(tests: str) -> tuple[int, str]:
    """``(pytest exit code, one line of evidence)``.

    Only exit code 1 means "a test failed". Codes 2-5 (collection error, internal error, usage, no tests) are what a
    mutant that merely breaks the syntax produces, and they prove nothing about the tests. A run that does not finish
    in time proves nothing either: a hang is reported as such, never counted as a kill.
    """
    env = {"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    for name in ("DATABASE_URL", "REDIS_URL"):
        if name in os.environ:
            env[name] = os.environ[name]
    try:
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-x",
                "-rf",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
                *tests.split(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=env,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return -1, f"no result after {TIMEOUT_SECONDS} s"
    lines = done.stdout.splitlines()
    failed = next((ln for ln in lines if ln.startswith("FAILED ")), "")
    if failed:
        evidence = failed.removeprefix("FAILED ").split(" - ")[0].split("::", 1)[-1]
    else:
        evidence = next((ln for ln in reversed(lines) if " passed" in ln or "error" in ln), "").strip()
    return done.returncode, evidence


def check_patterns(selected: list[Mutant]) -> int:
    bad = 0
    for mutant in selected:
        found = mutant.path.read_text(encoding="utf-8").count(mutant.old)
        if found != 1 or mutant.old == mutant.new:
            print(f"  [setup error] {mutant.name}: pattern occurs {found} times in {mutant.file}")
            bad += 1
    names = [x.name for x in selected]
    for name in {n for n in names if names.count(n) > 1}:
        print(f"  [setup error] two mutants are called {name!r}")
        bad += 1
    print(f"{len(selected)} patterns checked, {bad} problems")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-k", dest="keyword", default="", help="only mutants whose name contains this text")
    parser.add_argument("--check", action="store_true", help="only check that every pattern occurs exactly once")
    args = parser.parse_args()
    selected = [x for x in MUTANTS if args.keyword in x.name]
    if args.check:
        return check_patterns(selected)
    if check_patterns(selected):
        return 2

    # The unmutated suite must be green first, or "killed" would mean nothing.
    for tests in sorted({x.tests for x in selected}):
        code, summary = run_tests(tests)
        if code != 0:
            print(f"baseline is not green for {tests} (exit {code}): {summary}")
            return 2

    before = tree_hash()
    survivors: list[str] = []
    print(f"\n{len(selected)} mutants; each must turn its tests red\n")
    for mutant in selected:
        path = mutant.path
        original = path.read_text(encoding="utf-8")
        try:
            path.write_text(original.replace(mutant.old, mutant.new), encoding="utf-8")
            code, summary = run_tests(mutant.tests)
        finally:
            path.write_text(original, encoding="utf-8")
        if code == 1:
            print(f"  killed    {mutant.name}\n              by {summary}")
        elif code == 0:
            print(f"  SURVIVED  {mutant.name}   ({summary})")
            survivors.append(mutant.name)
        else:
            print(f"  INVALID   {mutant.name}: pytest exit {code}, the mutant did not run to a verdict ({summary})")
            survivors.append(mutant.name)

    if tree_hash() != before:
        print("\nSOURCE TREE CHANGED: restore it manually")
        return 3
    print(f"\nsource tree restored byte-for-byte; mutants {len(selected)}, survivors {len(survivors)}")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
