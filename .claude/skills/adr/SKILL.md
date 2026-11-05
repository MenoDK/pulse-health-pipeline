---
name: adr
description: Use when a decision is about to be made that a newcomer would have to reverse-engineer, such as a dependency, a data model, a boundary or a trade-off. Writes the ADR before the code.
---

# Architecture decision record

**Write it before implementing.** Afterwards it is a justification, not a decision.

1. Copy the shape of `docs/adr/0001-record-architecture-decisions.md`. Number it next, kebab-case title.
2. `Status:` Proposed, Accepted, Superseded by NNNN, Deprecated or Rejected.
3. **Context**: the forces and the measured facts, with the date of the measurement.
4. **Decision**: one paragraph, in the active voice.
5. **Rejected alternatives**: each with the reason it lost. An ADR that lists none is a changelog entry.
6. **Consequences**: what gets harder, and what you accept.
7. Add it to `docs/adr/README.md` and bump the count in the map in the same commit.

## Rules

- Supersede, never edit history: mark the old one `Superseded by NNNN` and say why.
- Prefer evidence to opinion: a benchmark, a failing test, a production incident.
- If the decision is reversible in an afternoon, it does not need an ADR.
