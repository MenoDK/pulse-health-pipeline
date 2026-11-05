# Agent contract

Tool-neutral: what any engineer or coding agent needs to work here without asking.

## Commands

| Task | Command |
| --- | --- |
| Install | `make install` (a virtualenv with the dev tools) |
| Lint, format, types, tests that need no service | `make check` |
| Every test, against real PostgreSQL + pgvector and Redis | `make test-integration` (starts them on loopback) |
| Break decisions on purpose | `make mutate` (must end `survivors 0`; rewrites `src/` while it runs) |
| The search evaluation, per kind of query | `make eval` |
| Run everything with the lab | `make demo`, then open http://localhost:8300 |
| Black-box checks against the running demo | `make smoke` |
| Browser tests (landing, lab, 14 languages, axe) | `make e2e` |
| The tour on the landing page still matches the code | `make transcripts-check` (`make transcripts` re-records) |
| Documentation guards | `docsguard check` |

## Definition of done

1. A test covers it and **fails without the change**; for a decision in the queue, sync, scoring or privacy, a mutant
   in `scripts/sabotage.py` dies without it.
2. `make check`, `make test-integration` and the documentation guards pass, and you can quote their output.
3. An ADR exists for any decision a newcomer would have to reverse-engineer, with the rejected alternatives.
4. `docs/HANDOFF.md` carries the numbers that were printed, not the ones that were expected.

## Boundaries

- Do not run `make mutate` while building a Docker image or editing `src/`: the script rewrites the source in place and
  restores it byte for byte.
- Do not store, log or print an identifying value. The privacy scan must stay clean.
- Do not weaken the production guard in `src/pulse/config.py`, and do not add a lab route that evaluates input.
- Do not edit an applied migration; add a new numbered one.
- Ask before adding a dependency or changing a public route.
- Anything outside the task goes into `docs/CHECKLIST.md`, not into this change.

## Reporting

Say what happened, not what was expected. A failed test, a skipped check or an unverified claim goes in the report as
it is. Retractions are written down, not quietly dropped.
