# Handoff

Updated: 2026-11-05

Rewritten at the end of every session. A fresh session must be able to resume from disk alone.

## 1. What is live

Nothing is deployed. `make demo` runs the stack locally (seven containers: `api`, `worker`, `beat`, `db` with pgvector,
`redis`, and the two stand-ins `registry` and `gateway`; `certs` and `migrate` run once) with the lab on, at
http://localhost:8300. Plain `docker compose up` runs the pipeline as it would run for real: no lab and no site.

## 2. Where we stopped

The pipeline, the landing page and the lab (`site/`), the browser tests (`e2e/`), the sabotage script, delivery files and
documentation are complete and verified locally. Open items are in the checklist.

## 3. What the owner does now

Push to GitHub and enable Actions: `.github/workflows/ci.yml` is linted (actionlint, hadolint) but has never run there. The
matrix is Python 3.11, 3.12 and 3.13; this was developed and measured on 3.14, so a 3.11 failure is possible and would be
real. Then ask someone who reads Hindi, Bengali, Urdu and Arabic to read the landing page: those translations are the
least certain.

## 4. Deadlines

None.

## 5. What NOT to do

- Do not replace the two claim queries (expired leases, then pending) by one with an `OR`: it reads and sorts the whole
  backlog. [ADR 0008](adr/0008-two-short-queries-instead-of-one-with-an-or.md); `test_schema.py` asserts the plan on 200 000 rows.
- Do not let a worker record a result without `locked_by` in the `WHERE`: that is the fence. [ADR 0002](adr/0002-a-queue-with-leases-and-fencing.md).
- Do not store a name, a national identifier, the registry's record id, a cursor id or a full birth date. The privacy scan in the
  lab and in `test_privacy.py` will fail, and that is the point. [ADR 0006](adr/0006-pseudonymise-and-keep-only-what-the-indicators-need.md).
- Do not let the sync position move backwards, and do not store anything but a time as the position. [ADR 0003](adr/0003-an-overlap-window-and-a-version-guard.md).
- Do not show a narrator's text that has not passed the number check, and do not loosen the check to make a test pass.
  [ADR 0005](adr/0005-a-check-between-the-model-and-the-number.md).
- Do not allow `LAB_MODE`, the demonstration keys or the stand-in controls outside development, and do not add a login to the
  lab: it is a local tool that answers only to `localhost`. [ADR 0007](adr/0007-a-lab-without-a-login-that-cannot-reach-production.md).
- Do not edit `site/transcripts.js` by hand: `make transcripts` records it from the running code, and `make transcripts-check`
  compares them.
- Do not put a script, font or stylesheet from another origin in `site/`; the Content Security Policy and the e2e suite refuse it.
- Do not change the figures on the landing page by hand: `make numbers` compares them with what the commands print.
- Do not hand-edit one language table to "fix" a string and leave the others: `site/i18n/<code>.js` mirrors `content.js`
  key for key (English is the source and the fallback). Strings that quote the lab's English buttons stay English on purpose.
- Do not give `beat` a health check on its schedule file, and do not "fix" the `ReadError` below by lengthening keep-alive:
  both were tried and disproved.

## 6. Decisions

- Queue, sync, ranking, the number check, pseudonyms, lab mode, claim queries: [ADR 0002](adr/0002-a-queue-with-leases-and-fencing.md) to
  [ADR 0008](adr/0008-two-short-queries-instead-of-one-with-an-or.md).
- Decisions are recorded as ADRs: [ADR 0001](adr/0001-record-architecture-decisions.md).

## 7. Learned, not in the code

- The recorded tour once claimed a duplicate that the run never produced (the queue tape said "refused" with a count of
  zero). `scripts/record_transcripts.py` now asserts what each caption says before it writes anything.
- A syntax error in `site/lab.js` (one missing parenthesis) passed every test that does not open a browser. `make site-syntax`
  (and the first CI step after the type check) now parses every script of the site.
- `docker compose up --wait` showed `worker` and `beat` unhealthy because the image's own `HEALTHCHECK` asks the API's port.
  The worker now checks itself with `celery inspect ping`. `beat` has no check: one on its schedule file's age failed 15 minutes
  into a healthy run, because the file is not rewritten while beat runs. Its evidence is the heartbeat it makes the worker
  write, which `/api/health` reports as `worker`. `healthcheck: { disable: true }` is needed, or the image's check applies.
- **Unexplained, unresolved:** after the lab's "Connect without it" (a rejected mutual-TLS handshake), the next call down the pooled,
  authenticated connection to the gateway fails once with `ReadError`. Reproduced by hand and in the browser tests (3 of 3
  runs). Not a keep-alive race (servers 30 s, client 5 s, still failed). An unauthenticated attempt from another container did
  not break the connection; one from the same process did. The lab's `gateway()` repeats a control call once, which is safe
  because they are idempotent, and `test_api.py` pins it. The pipeline is not affected.
- The first run on GitHub failed two mutual-TLS tests that had passed 550 times on the developer's machine: they named the exact
  exception a rejected client sees (`ReadError`), and on the runner the same refusal arrives as `RemoteProtocolError` (a closed
  connection instead of a TLS alert, which depends on timing and the TLS library). Both mean "the server said no after the
  handshake"; the client's own checks fail earlier as `ConnectError`. The tests accept the first two and the pipeline was never
  affected. Do not pin the exact name of a transport exception in a test.
- The first landing screenshot showed the hero's status card on top of the artwork. The overlays take roughly the top 70 and
  the bottom 160 pixels of the box, so the artwork lives between y = 130 and 505 of `viewBox="0 50 500 620"`; a test that measures
  labels inside the frame does not see an overlap with an element outside it.
- The demo's registry is generated "up to" a date, and the indicators age against it. `make demo` passes today's date
  (`STANDIN_AS_OF`) so a stack that has been up for a month still shows data inside the windows.
- Behaviour that nothing pinned until the sabotage script survived it: the position never moving backwards, taken-over
  being flagged on every claim instead of only after a dead worker, the lab's privacy sample showing a refused person, a
  stand-in ignoring `STANDIN_AS_OF`. Each now has a test that was seen failing first.
- Equivalent mutants exist and must be recognised: FastAPI serves no docs page without a schema URL, so publishing `docs_url`
  alone changes nothing. The script marks a mutant killed only when pytest exits 1; a timeout or any other exit is INVALID.

## 8. Suite state

Measured on 2026-11-05: 550 tests (281 need no service, 269 run against real PostgreSQL with pgvector and Redis), 158
sabotages, 50 black-box checks (`make smoke`), 65 browser tests (`make e2e`, against the compose stack: landing, lab, and the
14 languages, with axe scans in both themes), `ruff` clean, `mypy --strict` clean, `make numbers` and `make site-syntax` clean.
