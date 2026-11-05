"""Records the output shown in the landing page's tour by running the REAL pipeline on a scratch database.

Nothing on that page is typed by hand. Where the real command line is enough (`pulse sync`, `pulse search`, `pulse
eval`, `pulse indicators`) it is called, and only a `jq`-style projection of its JSON is applied, which the transcript
shows. Where the story needs the clock under control (a worker that dies, an hour that passes) the transcript is a
Python session: each `>>>` line is a real call and what follows is what the real objects print.

It needs the PostgreSQL the integration tests use (DATABASE_URL) and creates, uses and drops a database of its own on
that server. The two outside systems are the stand-ins from this repository, served on loopback.

    python scripts/record_transcripts.py            write site/transcripts.js
    python scripts/record_transcripts.py --check    record again and fail if site/transcripts.js no longer matches
"""

from __future__ import annotations

import contextlib
import html
import io
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pulse import cli  # noqa: E402
from pulse.clock import FixedClock  # noqa: E402
from pulse.config import Settings, get_settings  # noqa: E402
from pulse.exchange import queue  # noqa: E402
from pulse.exchange.worker import drain  # noqa: E402
from pulse.indicators.lab_narrators import NARRATORS  # noqa: E402
from pulse.indicators.narrative import narrate  # noqa: E402
from pulse.indicators.report import build_report  # noqa: E402
from pulse.privacy import find_values  # noqa: E402
from pulse.services import Services  # noqa: E402
from pulse.standin.gateway_app import create_gateway_app  # noqa: E402
from pulse.standin.registry_app import create_registry_app  # noqa: E402

OUT = ROOT / "site" / "transcripts.js"
SCRATCH = "pulse_tape"
AS_OF = "2026-06-30"
HEADER = (
    "/* Recorded from the real pipeline by scripts/record_transcripts.py. "
    "Do not edit: CI records again and compares. */\n"
)


class Server:
    """A stand-in served on loopback in a thread, like the integration tests do."""

    def __init__(self, app: Any) -> None:
        import socket

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = int(s.getsockname()[1])
        self.url = f"http://127.0.0.1:{self.port}"
        self._server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error"))
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> Server:
        self._thread.start()
        deadline = time.time() + 15
        while not self._server.started:
            if time.time() > deadline:
                raise RuntimeError("a stand-in did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(self.url + path, json=body, timeout=10)
        response.raise_for_status()
        return dict(response.json())

    def get(self, path: str) -> dict[str, Any]:
        response = httpx.get(self.url + path, timeout=10)
        response.raise_for_status()
        return dict(response.json())


class Tape:
    """Lines of a transcript. The kit inserts it as HTML, so every character is escaped when it is rendered."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    def say(self, line: str) -> None:
        if self.entries:
            self.entries.append(("", ""))
        self.entries.append(("tok-dim", f"# {line}"))

    def cli(self, shown: str, argv: list[str], keep: list[str] | None = None, *, nothing: str = "") -> None:
        """Run `pulse <argv>`. With `keep`, its JSON is projected to those keys, as the `jq -c` in `shown` would."""
        self.entries.append(("tok-k", f"$ {shown}"))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            cli.main(argv)
        printed = buffer.getvalue().rstrip("\n")
        if not printed:
            self.entries.append(("tok-dim", nothing or "(nothing is printed)"))
            return
        if keep is not None:
            data = json.loads(printed)
            printed = compact({item.partition("=")[0]: pick(data, item.rpartition("=")[2]) for item in keep})
        for line in printed.split("\n"):
            self.entries.append((colour(line), line))

    def py(self, code: str, result: str) -> None:
        self.entries.append(("tok-k", f">>> {code}"))
        for line in result.split("\n"):
            self.entries.append((colour(line), line))

    def render(self) -> str:
        out = []
        for cls, line in self.entries:
            shown = html.escape(line, quote=True)
            out.append(f'<span class="{cls}">{shown}</span>' if cls else shown)
        return "\n".join(out)


def pick(data: dict[str, Any], dotted: str) -> Any:
    """A path into the JSON the way jq spells it: `totals` or `totals.applied`."""
    value: Any = data
    for part in dotted.split("."):
        value = value[part]
    return value


def colour(line: str) -> str:
    if '"status":"failed"' in line or "refused" in line or "FOUND" in line:
        return "tok-bad"
    if "passed the check" in line or "found nothing" in line:
        return "tok-ok"
    return ""


def compact(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"))


def configure(registry_url: str, gateway_url: str, database_url: str) -> None:
    for key in list(os.environ):
        if key.startswith(("GATEWAY_", "REGISTRY_", "QUEUE_", "PSEUDONYM_", "LAB_", "STANDIN_")) or key == "SITE_DIR":
            del os.environ[key]
    os.environ.update(
        DATABASE_URL=database_url,
        REGISTRY_URL=registry_url,
        GATEWAY_URL=gateway_url,
        APP_ENV="development",
        PULSE_ROOT=str(ROOT),
    )
    get_settings.cache_clear()


def with_database(name: str, base: str) -> tuple[str, str]:
    url = make_url(base)
    return (
        url.set(database="postgres").set(drivername="postgresql+psycopg").render_as_string(hide_password=False),
        url.set(database=name).set(drivername="postgresql").render_as_string(hide_password=False),
    )


def record() -> dict[str, str]:
    base = os.environ.get("DATABASE_URL") or Settings(_env_file=None).database_url  # type: ignore[call-arg]
    admin_url, scratch_url = with_database(SCRATCH, base)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {SCRATCH}"))
    tapes: dict[str, str] = {}
    saved_env = dict(os.environ)
    try:
        with (
            Server(create_registry_app(seed=7, subjects=120, control=True)) as registry,
            Server(create_gateway_app(control=True)) as gateway,
        ):
            configure(registry.url, gateway.url, scratch_url)
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["migrate"])
                cli.main(["index"])
            services = Services(get_settings())
            engine = services.engine

            # ---- sync ---------------------------------------------------------------------------------------------
            t = Tape()
            summary = ["status", "queued", "totals"]
            t.say("A first run reads everything. Records that do not fit are counted, and never stored.")
            t.cli("pulse sync | jq -c '{status, queued, totals}'", ["sync"], summary)
            t.say("A second run re-reads a few minutes before the stored position, and writes nothing.")
            t.cli("pulse sync | jq -c '{status, queued, totals}'", ["sync"], summary)
            with engine.connect() as conn:
                position = conn.execute(
                    text("SELECT cursor_updated_at FROM sync_state WHERE entity = 'encounters'")
                ).scalar()
            now = position + timedelta(minutes=1)
            registry.post("/control/late-arrival", {"now": now.isoformat(), "behind_seconds": 120})
            t.say("A record is committed in the registry afterwards, stamped a minute before the stored position.")
            t.cli(
                "pulse sync | jq -c '{status, applied: .totals.applied}'",
                ["sync"],
                ["status", "applied=totals.applied"],
            )
            registry.post("/control/late-arrival", {"now": now.isoformat(), "behind_seconds": 3600})
            t.say("Another one, stamped almost an hour before it. The window does not reach back that far.")
            t.cli(
                "pulse sync | jq -c '{status, applied: .totals.applied}'",
                ["sync"],
                ["status", "applied=totals.applied"],
            )
            t.say("A full re-read ignores the stored position, finds it, and still writes nothing twice.")
            t.cli(
                "pulse sync --full | jq -c '{status, applied: .totals.applied}'",
                ["sync", "--full"],
                ["status", "applied=totals.applied"],
            )
            tapes["sync"] = t.render()

            # ---- queue --------------------------------------------------------------------------------------------
            t = Tape()
            clock = FixedClock(datetime.now(UTC))
            s = services.settings
            lease = s.queue_lease_seconds
            t.say("Every written encounter has a message, written in the same transaction.")
            t.py("queue.counts(engine)", str(queue.counts(engine)))
            taken = queue.claim(engine, worker="w1", now=clock.now(), limit=5, lease_seconds=lease)
            t.say("A worker claims five messages and dies without finishing.")
            t.py(
                'claim(engine, worker="w1", now=clock.now(), limit=5, lease_seconds=120)',
                f"ids {[m.id for m in taken]}, attempts {[m.attempts for m in taken]}",
            )
            t.py("queue.counts(engine)", str(queue.counts(engine)))
            clock.advance(600)
            t.say("Ten minutes later the lease has run out. The next worker takes those five over first.")
            first = drain(engine, services.gateway, clock, worker="w2", batch=10, lease_seconds=lease)
            t.py('drain(engine, gateway, clock, worker="w2", batch=10)', repr(first))
            gateway.post("/control/scenario", {"name": "lose-ack"})
            t.say("The gateway keeps each report and then fails to say so.")
            second = drain(engine, services.gateway, clock, worker="w2", batch=10, lease_seconds=lease)
            t.py('drain(engine, gateway, clock, worker="w2", batch=10)', repr(second))
            gateway.post("/control/scenario", {"name": "normal"})
            clock.advance(3600)
            t.say(
                "An hour later the gateway is well again and a worker takes everything that is due. Ten of those "
                "reports the gateway already holds: they are sent again with the same idempotency keys."
            )
            third = drain(engine, services.gateway, clock, worker="w2", batch=500, lease_seconds=lease)
            t.py('drain(engine, gateway, clock, worker="w2", batch=500)', repr(third))
            # The tape says what the code did, so the recording refuses to be written when that stops being true.
            assert first.taken_over == 5, first
            assert second.retried == 10 and second.delivered == 0, second
            assert third.duplicate == 10 and third.delivered == third.claimed - 10, third
            held = gateway.get("/control/state")
            assert held["duplicates"] == 10 and held["received_unique"] == queue.counts(engine)["done"], held
            t.say("The gateway holds each report once, and says how many repeats it was shown.")
            t.py(
                'gateway.state()["received_unique"], gateway.state()["duplicates"]',
                f"{held['received_unique']}, {held['duplicates']}",
            )
            tapes["queue"] = t.render()

            # ---- indicators ---------------------------------------------------------------------------------------
            t = Tape()
            t.say("Five counts in SQL, scored in exact arithmetic. This is the data the sync just loaded.")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                cli.main(["indicators", "--as-of", AS_OF, "--narrate"])
            printed = buffer.getvalue()
            report_json, _, words = printed.rpartition("}\n")
            data = json.loads(report_json + "}")
            t.entries.append(
                (
                    "tok-k",
                    f"$ pulse indicators --as-of {AS_OF} "
                    "| jq -c '.indicators[] | [.code, .numerator, .denominator, .percent, .status]'",
                )
            )
            for i in data["indicators"]:
                t.entries.append(
                    ("", compact([i["code"], i["numerator"], i["denominator"], i["percent"], i["status"]]))
                )
            t.entries.append(("tok-k", f"$ pulse indicators --as-of {AS_OF} --narrate | tail -n 1"))
            t.entries.append(("", words.rstrip("\n")))
            report = build_report(engine, datetime.fromisoformat(AS_OF).date()).to_dict()
            for mode, why in (
                (
                    "rounds",
                    "A narrator that rounds the first percentage, which reads better and is not what the report says.",
                ),
                ("invents", "A narrator that adds a forecast."),
                ("leaks", "A narrator that helpfully names a person."),
            ):
                t.say(why)
                result = narrate(report, NARRATORS[mode])
                t.py(
                    f'narrate(report, NARRATORS["{mode}"])',
                    "\n".join(
                        [
                            f"accepted {result.accepted} · text from the {result.source}",
                            *[f"refused: {v}" for v in result.violations],
                        ]
                    ),
                )
            tapes["indicators"] = t.render()

            # ---- search -------------------------------------------------------------------------------------------
            t = Tape()
            t.say("A word that is in a note: both lists find it, and the hybrid says where each hit came from.")
            t.cli(
                'pulse search "advisory lock" --mode hybrid -k 3',
                ["search", "advisory lock", "--mode", "hybrid", "-k", "3"],
            )
            t.say("A typo. The keyword index does not know the word.")
            t.cli(
                "pulse search synchronisaton --mode lexical",
                ["search", "synchronisaton", "--mode", "lexical"],
                nothing="(no note matches)",
            )
            t.say("The vectors compare spelling, so the typo lands next to the right notes.")
            t.cli(
                "pulse search synchronisaton --mode vector -k 3",
                ["search", "synchronisaton", "--mode", "vector", "-k", "3"],
            )
            t.say("Thirty-six labelled queries, four methods: recall@3 and MRR, overall and by kind of question.")
            t.cli("pulse eval", ["eval"])
            tapes["search"] = t.render()

            # ---- privacy ------------------------------------------------------------------------------------------
            t = Tape()
            people = registry.get("/control/identifiers?n=40")["people"]
            values = [v for p in people for v in (p["name"], p["national_id"], p["id"])]
            t.say(
                "The registry sends a name, a national identifier and an id. "
                f"Here are the first {len(people)} people's, fictitious."
            )
            t.py("[p['name'] for p in people[:3]]", str([p["name"] for p in people[:3]]))
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT subject_key, birth_month, team_id, chronic FROM subjects ORDER BY subject_key LIMIT 2")
                ).all()
            t.say("What is stored for people: a keyed hash, the month of birth, a team.")
            t.py(
                "SELECT subject_key, birth_month, team_id, chronic FROM subjects LIMIT 2",
                "\n".join(" | ".join(str(c) for c in r) for r in rows),
            )
            t.say("Look for every name, identifier and id, in every text, JSON and character column of every table.")
            clean = find_values(engine, values)
            t.py(f"find_values(engine, values)  # {len(values)} values", repr(clean))
            planted = people[3]["name"]
            with engine.begin() as conn:
                conn.execute(text("UPDATE sync_runs SET error = :n WHERE id = 1"), {"n": planted})
            t.say("To know the scan can see, write one of the names into a free-text column and look again.")
            found = find_values(engine, values)
            t.py(f"find_values(engine, values)  # after writing {planted!r} into sync_runs.error", repr(found))
            with engine.begin() as conn:
                conn.execute(text("UPDATE sync_runs SET error = NULL WHERE id = 1"))
            tapes["privacy"] = t.render()

            engine.dispose()
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)"))
        admin.dispose()
    return tapes


def render(tapes: dict[str, str]) -> str:
    return HEADER + "window.TRANSCRIPTS = " + json.dumps(tapes, indent=2, ensure_ascii=False) + ";\n"


def main() -> int:
    content = render(record())
    if "--check" in sys.argv:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != content:
            print(
                "site/transcripts.js does not match what the pipeline says: run scripts/record_transcripts.py",
                file=sys.stderr,
            )
            return 1
        print("transcripts match what the pipeline says")
        return 0
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
