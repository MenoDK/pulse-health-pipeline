# Read first: pulse-health-pipeline

This file is a **map, not content**. Open a document only when its row says to; that is what keeps a fresh
session cheap. Updated: 2026-11-05

| Open when you… | Document |
| --- | --- |
| start or resume a session | [HANDOFF](HANDOFF.md): where we stopped, what not to do |
| need to know what is planned, and in what order | [CHECKLIST](CHECKLIST.md) |
| ask "why is it built this way?" | [Decision records](adr/README.md) <!-- docsguard:count dir=docs/adr glob=0*.md expect=8 --> |
| are studying something unfamiliar | [Knowledge tree](knowledge-tree/README.md): open only the branch you need |
| must coordinate with another agent or tool | [Bridge protocol](bridge/PROTOCOL.md) |

## Rules of the map

1. **A new document is added here in the same commit that creates it.** A stale index is a defect, and
   `docsguard check --staged` refuses the commit that would leave one.
2. **Counts are verified, not trusted.** The marker above is compared with the disk on every run.
3. **One home per fact.** If it is in an ADR, link to the ADR. `CLAUDE.md` mirrors this map; if they diverge,
   fix `CLAUDE.md`.
4. **Dead documents move to `docs/archive/`** with a line saying how they ended. They are not deleted (the
   history is the evidence) and not mapped (they are not current).
