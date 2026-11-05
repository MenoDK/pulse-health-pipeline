# pulse-health-pipeline

A Python 3.11+ data pipeline between two systems that misbehave: it reads a registry in pages, stores only pseudonymised
records in PostgreSQL, scores indicators in exact arithmetic, and reports every change to a slow gateway through a queue
that survives crashes. The parts that fail in production (late records, dead workers, a down gateway, a model that
changes a number, a leak of identity) are real, tested against a real PostgreSQL, and can be provoked in the browser lab.

## Start here

- Map of every document: [docs/00-READ-FIRST.md](docs/00-READ-FIRST.md). Open a document only when the map says to.
- Resuming work: read `docs/HANDOFF.md` first. Before you stop, rewrite it.
- Commands and definition of done: @AGENTS.md

## Layout

- `src/pulse/sync.py`, `registry.py`: paged, resumable, late-arrival-tolerant synchronisation (ADR 0003).
- `src/pulse/exchange/`: the outbox queue, the drain loop, backoff, and the mTLS gateway client (ADR 0002, 0008).
- `src/pulse/indicators/`: SQL counts, exact scoring, and the narrator check (ADR 0005).
- `src/pulse/search/`: full-text, vector and rank-fusion search, with its labelled evaluation (ADR 0004).
- `src/pulse/identifiers.py`, `privacy.py`: pseudonyms, and the scan that proves nothing identifying is stored (ADR 0006).
- `src/pulse/api/`: FastAPI routes; `lab.py` and the Host/Origin gates exist only with `LAB_MODE` (ADR 0007).
- `src/pulse/standin/`: the stand-in registry and gateway that compose and the lab use. `synthetic.py` makes the data.
- `tests/`: real PostgreSQL and Redis. `scripts/sabotage.py` breaks decisions one at a time and requires a red test.
- `site/`: the landing page and the lab, plain files with no build step, in 14 languages. The tour on the landing page
  is recorded from the running code (`make transcripts`); never edit `site/transcripts.js` by hand.

## Rules that apply to every task

1. **Precedence when sources disagree:** code, then ADRs, then measured patterns, then this file.
2. **A decision a newcomer would have to reverse-engineer gets an ADR with the rejected alternatives.**
3. **A test must be seen failing without the change.** For a decision in the queue, the sync, the scoring or the privacy
   layer, add a mutant to `scripts/sabotage.py` too. Never write an assertion that cannot fail.
4. **No identifying value is ever stored or logged:** not the name, not the national identifier, not the registry id.
   An error message records the kind of failure, never a row.
5. **Numbers are computed in code, never by a model.** A narrator may only repeat them (ADR 0005).
6. **The lab never reaches production.** Do not weaken the configuration guard (ADR 0007).
7. **No literal credentials.** Secrets come from the environment at run time; tests build theirs.
8. **Docs are code.** A new document is added to the map in the same commit; `docsguard check` must pass.

Advice versus enforcement: this file is advice. If `docsguard` is installed, `.claude/settings.json` turns the key rules
into hooks (destructive git and writes to protected paths are refused).
