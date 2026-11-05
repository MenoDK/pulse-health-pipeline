"""The knowledge base the search runs over, and the labelled queries that evaluate it.

Thirty-six short notes about the pipeline itself, written for this repository. The queries were fixed before the first
evaluation was run, in five kinds, so the numbers cannot have been tuned to flatter one method:

* exact   a rare term that appears in the note;
* typo    the same idea with misspelled words;
* form    other word forms and partial overlap;
* gap     no shared words at all (a vector of letters cannot bridge this, and the evaluation says so);
* natural a full sentence, as a person asks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Doc:
    doc_id: str
    title: str
    category: str
    text: str


@dataclass(frozen=True)
class LabelledQuery:
    kind: str
    query: str
    relevant: frozenset[str]


DOCS: tuple[Doc, ...] = (
    Doc(
        "kb-01",
        "Resuming an interrupted synchronisation",
        "operations",
        "A synchronisation run commits each page together with its position. If the process stops, the next run reads the "
        "stored position and continues from there; nothing is fetched twice except the overlap window.",
    ),
    Doc(
        "kb-02",
        "Why the overlap window exists",
        "operations",
        "A record can become visible in the registry after another record with a later timestamp. The run therefore starts "
        "a few minutes before the stored position and relies on the version check to ignore what it has already applied.",
    ),
    Doc(
        "kb-03",
        "Version check on every write",
        "data-quality",
        "A row is overwritten only when the incoming version is newer than the stored one. An old copy of a record "
        "replayed by a retry cannot replace a corrected record.",
    ),
    Doc(
        "kb-04",
        "Teams listed twice",
        "data-quality",
        "The registry sometimes lists the same team under two identifiers. The team code is the business key, so the "
        "duplicate collapses into one row and the newest version wins.",
    ),
    Doc(
        "kb-05",
        "Rejected records",
        "data-quality",
        "A person whose national identifier fails its check digits is rejected and counted, never stored. Rejections are "
        "reported in the run summary without the content of the record.",
    ),
    Doc(
        "kb-06",
        "Pseudonymisation of people",
        "privacy",
        "People are stored under a keyed hash of the registry identifier. The key is configured outside the database, so a "
        "leaked copy of the analytic tables cannot be joined back to the registry.",
    ),
    Doc(
        "kb-07",
        "Rotating the pseudonym key",
        "privacy",
        "Each subject key carries the identifier of the key that produced it. To rotate, configure the new key, re-key the "
        "rows in a migration while the old key is still available, then retire the old key.",
    ),
    Doc(
        "kb-08",
        "Data minimisation of birth dates",
        "privacy",
        "Only the birth month is kept. An age band needs no more precision, and a full date of birth combined with a team "
        "is much easier to link to one person.",
    ),
    Doc(
        "kb-09",
        "Names and national identifiers are not stored",
        "privacy",
        "Names and national identifiers are read, validated and dropped at the edge. No table has a column for them, and a "
        "test searches the whole database for the values it generated.",
    ),
    Doc(
        "kb-10",
        "The transmission queue",
        "integration",
        "Each new or corrected encounter is queued for the gateway in the same transaction that stores it. Delivery is at "
        "least once; the idempotency key makes the effect exactly once.",
    ),
    Doc(
        "kb-11",
        "Lease and recovery of a crashed worker",
        "integration",
        "A worker claims messages with a lease. If the worker dies, the lease runs out and another worker takes the "
        "messages again. Attempts are counted when a message is claimed, so a message that always kills its worker ends up "
        "dead.",
    ),
    Doc(
        "kb-12",
        "Retry delays",
        "integration",
        "Delays grow exponentially up to a cap, spread with a jitter derived from the message key. Messages that failed "
        "together do not all retry together.",
    ),
    Doc(
        "kb-13",
        "Permanent and temporary failures",
        "integration",
        "A payload the gateway refuses with 400 or 422 is dead at once. A gateway outage, an expired token or a revoked "
        "credential is not the message's fault, so the message waits.",
    ),
    Doc(
        "kb-14",
        "Lost acknowledgement",
        "integration",
        "The gateway can store a report and fail to answer. The sender retries and receives a duplicate answer, which "
        "counts as delivered. The report exists once.",
    ),
    Doc(
        "kb-15",
        "Outage handling",
        "operations",
        "After three transport failures in a row a worker stops and releases the rest of its batch without spending their "
        "attempts, so a long outage does not bury the queue in dead letters.",
    ),
    Doc(
        "kb-16",
        "Token refresh under concurrency",
        "integration",
        "Many threads can need a token at the same moment. One of them fetches it; the others wait and reuse it. A "
        "rejected token is invalidated only if it is still the cached one.",
    ),
    Doc(
        "kb-17",
        "Client certificate authentication",
        "integration",
        "The connection to the gateway presents a client certificate. When the handshake fails the sender records a "
        "transport error with the exception name and retries later.",
    ),
    Doc(
        "kb-18",
        "Indicators are computed in code",
        "indicators",
        "Numerators and denominators are counted in SQL and scored with exact fractions. A language model may describe the "
        "result but is never asked to calculate.",
    ),
    Doc(
        "kb-19",
        "Zero is not missing",
        "indicators",
        "A numerator of zero is a result of zero percent. Only a denominator of zero means there was nobody to measure, and "
        "such an indicator is left out of the score and reported as excluded.",
    ),
    Doc(
        "kb-20",
        "Bands and targets",
        "indicators",
        "An indicator is excellent at or above its target, good from ninety percent of it, fair from seventy percent, and "
        "poor below. Targets and weights here are illustrative.",
    ),
    Doc(
        "kb-21",
        "Rounding of the overall score",
        "indicators",
        "The overall score is a fraction rounded half up once, at the end. No floating point number takes part, so two "
        "machines cannot disagree on the second decimal.",
    ),
    Doc(
        "kb-22",
        "Checking the narration",
        "indicators",
        "Before a narration is shown, every number in it must appear in the report in the same form. A text with a "
        "different number is replaced by the template text and the reason is shown.",
    ),
    Doc(
        "kb-23",
        "Hybrid search",
        "search",
        "Keyword search finds exact terms and rare codes. Vector search tolerates misspellings and word forms. The two "
        "ranked lists are combined by reciprocal rank fusion.",
    ),
    Doc(
        "kb-24",
        "Why not add the scores",
        "search",
        "Keyword scores and vector similarities live on different scales. A weighted sum of raw scores lets one side "
        "dominate whatever the weights say, so ranks are fused instead.",
    ),
    Doc(
        "kb-25",
        "Approximate nearest neighbour index",
        "search",
        "An HNSW index answers nearest neighbour queries without scanning every chunk. It is approximate, so recall is "
        "measured on a labelled set rather than assumed.",
    ),
    Doc(
        "kb-26",
        "The embedding used here",
        "search",
        "Character trigrams are hashed into a fixed number of dimensions. It captures spelling and word forms, not "
        "meaning; a paraphrase with no shared letters will be missed.",
    ),
    Doc(
        "kb-27",
        "Health of the pipeline",
        "operations",
        "Health is reported per component: database, broker, worker heartbeat, queue age, last successful synchronisation, "
        "search index. The database and the broker are critical; the rest degrade the status.",
    ),
    Doc(
        "kb-28",
        "The worker heartbeat",
        "operations",
        "A scheduled task writes a heartbeat. If it is older than three intervals the worker is reported as down, which "
        "also reveals a stopped scheduler.",
    ),
    Doc(
        "kb-29",
        "Oldest message age",
        "operations",
        "A queue that is long but moving is healthy; one whose oldest due message is old is not. The age of the oldest due "
        "message is a better alarm than the depth.",
    ),
    Doc(
        "kb-30",
        "Full reconciliation",
        "operations",
        "A record that appears later than the overlap window with an earlier timestamp is not seen by an incremental run. "
        "A full run re-reads everything, and the version check makes it safe.",
    ),
    Doc(
        "kb-31",
        "Single run at a time",
        "operations",
        "An advisory lock keeps two synchronisation runs apart. The second reports that it was skipped instead of waiting "
        "or racing the first.",
    ),
    Doc(
        "kb-32",
        "Withdrawn records",
        "data-quality",
        "A record withdrawn in the registry arrives as a deleted version. It stays as a tombstone, is excluded from every "
        "indicator, and is reported to the gateway as a deletion.",
    ),
    Doc(
        "kb-33",
        "Synthetic data",
        "operations",
        "All data in this repository is generated from a seed: names from syllables, identifiers with valid check digits. "
        "Nothing is derived from a real person.",
    ),
    Doc(
        "kb-34",
        "Time as an argument",
        "operations",
        "Every wait reads a clock that is passed in. Tests and the lab move time forward instead of sleeping, so a backoff "
        "of hours is checked in milliseconds.",
    ),
    Doc(
        "kb-35",
        "Production refusals",
        "operations",
        "In production the service refuses the demonstration API key, the demonstration pseudonym key and the lab. It "
        "stops at start with a message naming the setting.",
    ),
    Doc(
        "kb-36",
        "Page order check",
        "data-quality",
        "A page whose records are not in non-decreasing order of timestamp and identifier makes the stored position "
        "unreliable, so the run fails instead of continuing.",
    ),
)


def _q(kind: str, query: str, *relevant: str) -> LabelledQuery:
    return LabelledQuery(kind, query, frozenset(relevant))


QUERIES: tuple[LabelledQuery, ...] = (
    # exact: a rare term from the note
    _q("exact", "advisory lock", "kb-31"),
    _q("exact", "HNSW", "kb-25"),
    _q("exact", "reciprocal rank fusion", "kb-23", "kb-24"),
    _q("exact", "idempotency key", "kb-10"),
    _q("exact", "check digits", "kb-05", "kb-33"),
    _q("exact", "tombstone", "kb-32"),
    _q("exact", "heartbeat", "kb-28", "kb-27"),
    _q("exact", "lease", "kb-11"),
    _q("exact", "jitter", "kb-12"),
    _q("exact", "half up", "kb-21"),
    # typo: the same idea, misspelled
    _q("typo", "pseudonimization key rotaton", "kb-07", "kb-06"),
    _q("typo", "synchronisaton resume interupted", "kb-01"),
    _q("typo", "recipricol rank fuzion", "kb-23"),
    _q("typo", "tranmission queu", "kb-10"),
    _q("typo", "heartbeet", "kb-28", "kb-27"),
    _q("typo", "birth montth precission", "kb-08"),
    _q("typo", "natonal identifer rejected", "kb-05"),
    _q("typo", "certifcate handshak", "kb-17"),
    # form: other word forms, partial overlap
    _q("form", "retrying failed messages with longer delays", "kb-12"),
    _q("form", "workers crashing while sending", "kb-11"),
    _q("form", "duplicated teams in the registry", "kb-04"),
    _q("form", "scores are rounded", "kb-21"),
    _q("form", "tokens refreshed by several threads", "kb-16"),
    _q("form", "outages and dead messages", "kb-15", "kb-13"),
    _q("form", "keys rotated", "kb-07"),
    _q("form", "indicators calculated by the model", "kb-18"),
    # gap: no shared words
    _q("gap", "what do we do when the national service is unreachable for hours", "kb-15", "kb-13"),
    _q("gap", "how do we know the person on call should wake up", "kb-29"),
    _q("gap", "stop a stale copy from clobbering a fix", "kb-03"),
    _q("gap", "can someone link a leaked table back to a patient", "kb-06", "kb-08"),
    _q("gap", "is the story the machine writes allowed to invent figures", "kb-22", "kb-18"),
    # natural: a sentence as a person asks it
    _q("natural", "what happens to a message if the worker dies after claiming it", "kb-11"),
    _q("natural", "how does the pipeline avoid reporting the same encounter twice to the gateway", "kb-14", "kb-10"),
    _q("natural", "why is a score of zero percent different from having no data", "kb-19"),
    _q("natural", "which components make the health status critical", "kb-27"),
    _q("natural", "how are older versions of a record kept from overwriting newer ones", "kb-03"),
)
