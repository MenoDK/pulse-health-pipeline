# ADR 0003: An overlap window and a version guard

Status: Accepted

## Context
The source registry offers one thing: pages of records ordered by `(updated_at, id)`. It does not push, and a record can
become visible *after* a later one (a transaction that committed late). A synchronisation that asks only for "newer than
what I saw" loses those records without a trace. It must also be safe to run again at any time, and to die half way.

## Decision
1. **Page by keyset, not by offset**, on `(updated_at, id)`. Inside one run the position moves strictly forward in memory,
   so a page boundary cannot split records that share a timestamp.
2. **Between runs only a time is stored.** The next run starts `overlap_seconds` (300) *before* it and re-reads whatever
   the window covers, including records that share the stored timestamp. A registry record id is never written to our
   database for this (see ADR 0006).
3. **A version guard makes the re-read harmless.** A record is applied only when its version is newer (`_newer`); an equal
   or older one is counted as `stale`. Replaying everything changes nothing and queues nothing.
4. **A page and the position that follows it are committed together.** A crash leaves a consistent state; the next run
   resumes from the last committed page. The end state equals an uninterrupted run (tested).
5. **The stored position never moves backwards** (`_advance` writes only a later time). When the registry has lost its
   newest records, a re-read of the window would otherwise pull the position back a little more on every run.
6. **A full reconcile exists** (`pulse sync --full`): it ignores the position and offers every record again. The version
   guard keeps it safe.
7. **A page out of order, or without a readable position, fails the run** instead of guessing.

## Rejected alternatives
- **`updated_at > stored`.** The simplest rule loses late commits and records sharing a timestamp across a page boundary.
  A test shows a record one minute late being lost without the window.
- **Store `(time, id)` as the position.** It removes the need for the window's tie handling, but it keeps a registry
  identifier in our database for no gain once the window and the guard are there.
- **Offset paging.** The pages shift while the registry changes, so records are skipped or repeated.
- **Always re-read everything.** Correct and expensive: the cost grows with the whole history. It stays as the reconcile.
- **Ask the registry for change events.** It does not offer them.

## Consequences
- (+) Resumable, idempotent, and tolerant of late commits inside the window.
- (+) The cost of a run follows what changed, not the size of the history.
- (−) **A record that arrives later than the window is not seen until a full reconcile.** This is stated, tested, and
  listed in the README; the window is a setting.
- (−) Each run re-reads the window (a few records) on purpose.
