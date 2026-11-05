"""`pulse`: the pipeline from a terminal. The same functions the API and the workers call, nothing else."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from pulse.config import get_settings
from pulse.services import Services


def _migrate() -> int:
    from alembic import command
    from alembic.config import Config

    # Run from the folder that holds alembic.ini: the repository root, or /app in the image.
    root = Path(os.environ.get("PULSE_ROOT", ".")).resolve()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")
    print("schema is at head")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pulse", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="create or upgrade the schema")
    sub.add_parser("index", help="(re)build the search index from the built-in notes")
    p_sync = sub.add_parser("sync", help="run one synchronisation from the registry")
    p_sync.add_argument("--full", action="store_true", help="ignore the stored position and re-read everything")
    sub.add_parser("drain", help="send what is due in the transmission queue")
    p_requeue = sub.add_parser("requeue", help="give dead messages another full set of attempts")
    p_requeue.add_argument("ids", nargs="*", type=int, help="message ids; none means every dead message")
    p_ind = sub.add_parser("indicators", help="print the indicator report")
    p_ind.add_argument("--as-of", type=date.fromisoformat, default=None)
    p_ind.add_argument("--narrate", action="store_true")
    p_search = sub.add_parser("search", help="search the notes")
    p_search.add_argument("query")
    p_search.add_argument("--mode", choices=["lexical", "vector", "hybrid", "weighted"], default="hybrid")
    p_search.add_argument("-k", type=int, default=5)
    sub.add_parser("eval", help="evaluate every search mode on the labelled queries")
    args = parser.parse_args(argv)

    if args.command == "migrate":
        return _migrate()

    services = Services(get_settings())
    if args.command == "index":
        from pulse.search.store import index_documents

        print(f"indexed {index_documents(services.engine, services.embedder)} chunks")
    elif args.command == "sync":
        from pulse.api.routes import sync_dict

        print(json.dumps(sync_dict(services.syncer().run(full=args.full)), indent=2))
    elif args.command == "drain":
        from dataclasses import asdict

        from pulse.exchange.worker import drain

        s = services.settings
        report = drain(
            services.engine,
            services.gateway,
            services.clock,
            worker="cli",
            batch=s.queue_batch,
            lease_seconds=s.queue_lease_seconds,
            max_attempts=s.queue_max_attempts,
            backoff_base=s.queue_backoff_base_seconds,
            backoff_cap=s.queue_backoff_cap_seconds,
        )
        print(json.dumps(asdict(report), indent=2))
    elif args.command == "requeue":
        from pulse.exchange.queue import requeue_dead

        print(f"requeued {requeue_dead(services.engine, services.clock.now(), ids=args.ids or None)} messages")
    elif args.command == "indicators":
        from pulse.indicators.narrative import TemplateNarrator, narrate
        from pulse.indicators.report import build_report

        report_dict = build_report(services.engine, args.as_of or services.clock.now().date()).to_dict()
        print(json.dumps(report_dict, indent=2))
        if args.narrate:
            print(narrate(report_dict, TemplateNarrator()).text)
    elif args.command == "search":
        from pulse.search.store import search

        for hit in search(services.engine, services.embedder, args.query, args.mode, k=args.k):
            print(f"{hit.score:8.4f}  {hit.doc_id}  {hit.title}  {hit.ranks}")
    elif args.command == "eval":
        from pulse.search.evaluate import evaluate, render

        print(render(evaluate(services.engine, services.embedder)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
