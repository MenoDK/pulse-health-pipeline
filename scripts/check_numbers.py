#!/usr/bin/env python3
"""The landing page prints four figures. Fail when one of them is not what the repository says today.

    python scripts/check_numbers.py

Each figure is read from the page (site/content.js, `under.numbers`) and compared with the command that produces it:
the tests pytest collects, the mutants the sabotage script holds, the labelled search queries, the decision records.
Nothing here needs a database.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse.search.corpus import QUERIES  # noqa: E402


def run(*command: str) -> str:
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"{' '.join(command)} failed:\n{done.stdout}{done.stderr}")
    return done.stdout


def printed() -> dict[str, int]:
    """The figure on the page beside each of its captions, keyed by a word of the caption."""
    source = (ROOT / "site" / "content.js").read_text(encoding="utf-8")
    block = re.search(r"numbers:\s*\[(.*?)\n\s*\],", source, re.S)
    if block is None:
        raise SystemExit("site/content.js has no `numbers` list")
    rows = re.findall(r"\[\s*'(\d+)'\s*,\s*'([^']*)'\s*\]", block.group(1))
    found: dict[str, int] = {}
    for word in ("tests", "sabotages", "labelled", "decision"):
        match = [int(figure) for figure, caption in rows if caption.startswith(word)]
        if len(match) != 1:
            raise SystemExit(f"expected exactly one figure whose caption starts with '{word}', found {match}")
        found[word] = match[0]
    return found


def actual() -> dict[str, int]:
    collected = re.search(r"(\d+) tests? collected", run(sys.executable, "-m", "pytest", "--collect-only", "-q"))
    mutants = re.search(r"(\d+) patterns checked", run(sys.executable, "scripts/sabotage.py", "--check"))
    if collected is None or mutants is None:
        raise SystemExit("could not read the number of tests or of mutants from their commands")
    return {
        "tests": int(collected.group(1)),
        "sabotages": int(mutants.group(1)),
        "labelled": len(QUERIES),
        "decision": len(list((ROOT / "docs" / "adr").glob("0*.md"))),
    }


def main() -> int:
    on_page, in_repo = printed(), actual()
    wrong = [word for word in on_page if on_page[word] != in_repo[word]]
    for word in on_page:
        mark = "ok " if word not in wrong else "FAIL"
        print(f"  {mark} {word:<10} page says {on_page[word]:>4}   repository has {in_repo[word]:>4}")
    if wrong:
        print("\nUpdate `under.numbers` in site/content.js (and the translations do not hold figures, so only there).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
