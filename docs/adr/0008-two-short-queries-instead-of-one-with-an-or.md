# ADR 0008: Two short claim queries instead of one with an OR

Status: Accepted

## Context
A claim must find the next due messages among a table that keeps growing: finished messages stay (the attempt log is the
audit trail), so the table is mostly `done`. "Due" means two things: a pending message whose time has come, or a message
whose worker's lease ran out. The first version expressed that as one query with an `OR`.

## Decision
**Two queries, each answered by its own partial index, in index order, with `LIMIT`.** Messages whose worker died are
read first (they have waited longest), then pending ones, only up to the room left in the batch.

```
EXPIRED  status = 'sending' AND lease_until < :now   ORDER BY lease_until, id   -- outbox_lease_idx
PENDING  status = 'pending' AND not_before <= :now   ORDER BY not_before, id    -- outbox_due_idx
```

A claim therefore reads about `limit` rows however large the backlog is. It is a test of the *plan*, not of the clock: on
200 000 messages (95 % finished, 2 % due, 2 % held by a dead worker) each query must use an index scan, no sort and no
sequential scan, and stop at the 50 rows asked for.

## Rejected alternatives
- **One query with an `OR`.** PostgreSQL cannot walk two indexes in order for it. It read and sorted every due row
  (10 000 in the test) to return 50, so a claim cost grew with the backlog. This was measured, and it is what the test
  was written against.
- **A single index on `(status, not_before)`.** The two conditions order by different columns; one index serves one.
- **A time threshold in the test** ("under 50 ms"). A clock assertion is flaky on a busy machine and proves nothing about
  why it is fast. The plan is deterministic.
- **Delete finished messages.** It would keep the table small, and it would throw away the delivery history. Nothing
  here deletes them; archiving old rows is listed as future work, not built.

## Consequences
- (+) A claim stays cheap as the table grows, and the property is a test that fails if someone merges the queries again.
- (+) Taken-over messages are known at claim time, so the drain report can say how many came from a dead worker
  (`taken_over`). The lab shows it.
- (−) Two round trips instead of one when both kinds are due. Negligible next to the delivery they precede.
- (−) Two partial indexes to maintain on every status change.
