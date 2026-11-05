# Master checklist

*What* and *when*. The *how* belongs in a task's own notes, with `path:line` evidence; the *why* in an ADR.

| # | Item | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Adopt decision records | done | [ADR 0001](adr/0001-record-architecture-decisions.md) |
| 2 | Incremental sync: keyset paging, overlap window, version guard, a position that never moves backwards | done | [ADR 0003](adr/0003-an-overlap-window-and-a-version-guard.md), `tests/test_sync.py` |
| 3 | Transactional outbox with leases, fencing and a bounded claim | done | [ADR 0002](adr/0002-a-queue-with-leases-and-fencing.md), [ADR 0008](adr/0008-two-short-queries-instead-of-one-with-an-or.md), `tests/test_queue.py`, `tests/test_schema.py` |
| 4 | Delivery over OAuth and mutual TLS with an idempotency key, and the stop rule | done | `tests/test_gateway.py`, `tests/test_mtls.py`, `tests/test_worker.py` |
| 5 | Five indicators with exact scoring, and the number check between a model and a number | done | [ADR 0005](adr/0005-a-check-between-the-model-and-the-number.md), `tests/test_scoring.py`, `tests/test_narrative.py` |
| 6 | Search over pgvector and `tsvector`, rank and weighted fusion, the labelled evaluation | done | [ADR 0004](adr/0004-rank-fusion-over-a-weighted-sum.md), `tests/test_search.py`, `pulse eval` |
| 7 | Pseudonyms, birth month only, and the whole-database scan | done | [ADR 0006](adr/0006-pseudonymise-and-keep-only-what-the-indicators-need.md), `tests/test_privacy.py` |
| 8 | Lab, stand-ins, landing page in 14 languages, refused in production | done | [ADR 0007](adr/0007-a-lab-without-a-login-that-cannot-reach-production.md), `tests/test_api.py`, `site/` |
| 9 | Sabotage script: every decision is proven by a break that must turn a test red | done | `scripts/sabotage.py` (158 sabotages, 0 survivors on 2026-11-05) |
| 10 | Containers, health-gated compose, black-box smoke test | done | `Dockerfile`, `docker-compose.yml`, `scripts/smoke.sh` (50 checks) |
| 11 | Browser tests with accessibility scans in both themes and 14 languages | done | `e2e/`, `make e2e` (65 tests) |
| 12 | CI workflow | done | `.github/workflows/ci.yml`: all eight jobs green on GitHub (run 42024939607, commit 05bfd73); the first two runs found two CI-only bugs, see HANDOFF §7 |
| 13 | A sentence embedder behind the existing `Embedder` interface | todo | the `gap` row of `pulse eval` is the case it would improve |
| 14 | A re-keying job for pseudonyms | todo | the key id is stored with every pseudonym; ADR 0006 |
| 15 | A reconciliation count against the registry, to notice what the overlap window cannot | todo | ADR 0003; `pulse sync --full` is the manual remedy |
| 16 | Backups and a restore drill for the database | dropped | left to the platform the service runs on; README "Limitations" |

Status is one of `todo`, `doing`, `done`, `dropped`. A `done` row names the commit, test or document that proves it.
A row is never deleted when it is dropped: it is marked `dropped` with the reason.
