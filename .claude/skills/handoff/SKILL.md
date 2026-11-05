---
name: handoff
description: Use when ending a session, switching agents, or resuming work after a break. Rewrites docs/HANDOFF.md so a fresh session can continue from disk alone.
---

# Handoff

**Rewrite `docs/HANDOFF.md`; do not append to it.** A handoff that only grows stops being read.

Eight sections, all required (`docsguard check` enforces them):

1. **What is live**: what runs, where, at which version.
2. **Where we stopped**: the exact file and step, not "mostly done".
3. **What the owner does now**: the actions only a human can take.
4. **Deadlines**: dates that change priorities.
5. **What NOT to do**: the traps you already fell into.
6. **Decisions**: each with a link to its ADR, or `none`.
7. **Learned, not in the code**: facts that cost time and are invisible in the diff.
8. **Suite state**: the numbers the checks printed *now*.

## Rules

- Report what happened, not what was expected. If a test failed or a check was skipped, say so.
- A retraction goes in the document: write what you had claimed and what turned out true.
- Never put a secret in it. Refer to one by `sha256 | cut -c1-12`.
- Update the `Updated:` date and the map in the same commit.

## Test

Could a session that has read nothing else resume from this file alone? If not, it is not finished.
