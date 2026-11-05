# ADR 0002: A transmission queue with leases and fencing, in the same database

Status: Accepted

## Context
Every change the pipeline stores has to be reported to a downstream gateway that is slow, sometimes down, and answers
over HTTP, so the answer can be lost after the work was done. Three things must hold: a change is never stored without
its message (or the reverse), a worker that dies loses nothing, and a worker that was thought dead but is only slow
must not undo the work of the one that took over.

## Decision
1. **The message is written in the transaction of the change** (`enqueue_many` takes the caller's connection). The
   idempotency key is unique; queueing a key twice is a no-op.
2. **A claim takes due messages with `FOR UPDATE SKIP LOCKED` and a lease.** Workers never wait for each other. A
   worker that dies leaves its messages in `sending` until the lease runs out, then they are due again.
3. **Attempts are counted when the message is claimed, not when it fails.** A message that kills its worker every time
   still reaches `dead` instead of looping forever (`reap_exhausted`).
4. **Every state change after a claim names the worker** (`locked_by`). `finish` returns `False` when the lease was
   taken over, and the late result is discarded: this is fencing.
5. **Delivery is at least once; the gateway removes the duplicates** with the idempotency key. A "duplicate" answer is
   a success.
6. **Backoff has a deterministic jitter**, and a run stops after three consecutive *transport* failures (no answer at
   all) and gives the unsent messages back without spending their attempt. An answer from the gateway, even a 503, is
   not an outage.
7. **`dead` is a state a person looks at, not a grave**: `pulse requeue` gives a fresh set of attempts.

## Rejected alternatives
- **Celery or a Redis list as the queue itself.** The message and the change could not commit together, and the broker
  here keeps nothing on disk. Celery stays what it is good at: the clock (it triggers `drain`), not the source of truth.
- **Write the change, then publish the message (dual write).** A crash in between loses the message. The outbox is
  the only way to make the two one decision.
- **A visibility timeout with no fencing.** A slow worker that wakes up after its lease was taken over would overwrite
  the delivery with its stale failure. The test `a_worker_that_lost_its_lease_cannot_overwrite_the_one_that_took_over`
  fails without the `locked_by` condition.
- **Claim "exactly once".** Not available over HTTP: the answer can be lost after the work was done. The honest
  contract is at-least-once plus an idempotency key.
- **Counting the attempt when it fails.** A worker killed mid-send would never count the attempt, and a poison message
  would be retried forever.

## Consequences
- (+) No message is lost to a crash, a restart or a broker loss; the database is the only source of truth.
- (+) Several workers share the load without coordinating.
- (−) Throughput is bounded by PostgreSQL. That is far above what this volume needs; a broker with its own log would
  be the next step, and the claim/finish interface is the seam.
- (−) A worker that stops answering costs one lease interval of delay before its messages move.
