# 0001. Record architecture decisions

Status: Accepted

## Context

Decisions made in a chat, a pull-request thread or somebody's head are lost within weeks. A new engineer, or a
fresh AI session with no memory, then has to reverse-engineer the *why* from the code, and the code only shows
the *what*. Re-deciding what was already settled costs more than writing it down.

## Decision

Every decision that a newcomer would otherwise have to reverse-engineer gets a short record in `docs/adr/`,
written before the implementation, with the alternatives that lost and the reason each lost. Records are
immutable once accepted: a change of mind is a new record that supersedes the old one.

## Rejected alternatives

- **Rely on commit messages.** They record what changed, are not searchable by topic, and carry no
  rejected alternatives.
- **A wiki outside the repository.** It drifts from the code and cannot fail a build.
- **No records, trust the code.** Cheapest today; the cost is paid by every future reader, repeatedly.

## Consequences

A little writing before each significant change. In return, a session that reads one short file knows what is
settled, and `docsguard` can verify the records are complete and indexed.
