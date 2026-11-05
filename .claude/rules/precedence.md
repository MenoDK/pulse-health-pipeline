# Precedence and instruction hygiene

Unscoped on purpose: this file has no `paths:` front matter, so it is loaded in every session and survives
`/compact`. Keep it short; everything here is paid for on every turn.

## When two sources disagree

1. **The code**: it is what runs. If a document contradicts it, fix the document.
2. **ADRs** (`docs/adr/`): why it is built this way. A newer ADR supersedes an older one explicitly.
3. **Measured patterns**: conventions backed by a number or a test, not by taste.
4. **CLAUDE.md**, then **AGENTS.md**: advice and contract. The map (`docs/00-READ-FIRST.md`) is the source for
   *where things are*; CLAUDE.md only mirrors it, and when they diverge the mirror is wrong.

## Budget

- Per file loaded at startup: stay under ~200 lines. Past that, instructions are followed less reliably.
- Put the instruction that matters most at the top of a file or skill. After compaction a skill body is
  truncated, and the end is what is lost.
- Detail belongs in on-demand documents. If you are about to paste a page into CLAUDE.md, link it instead.

## Advice versus enforcement

"Never do X" in a markdown file is a request. A hook that denies X is a rule. If a mistake has happened twice,
stop writing it down and make it fail the build: see the `guards` skill.
