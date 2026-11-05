# Bridge protocol

How two agents or tools (a coding agent and a desktop assistant, say) coordinate through files, not through memory.

1. **One author per file.** Each file under `docs/bridge/` has a single writer; others read it.
2. **A living document, rewritten.** Not an accumulating log. Old state is overwritten; history is in git.
3. **It opens with a state block:** 🟢 working, 🟠 degraded, ⚪ not started, 🔴 broken, one line each.
4. **Secrets never cross.** Refer to one by `sha256 | cut -c1-12`, enough to tell two apart and nothing else.
5. **Personal data never crosses.** Describe its shape, not its content.
6. **A decision counts only once it is in an ADR or the checklist.** A message saying "we agreed" is not a decision.
7. **Plans are dated** (`PLAN-2026-01-31.md`); a dead plan moves to `docs/archive/` with a line on how it ended.

Test: if the other agent restarted with no memory, could it continue from these files alone?
