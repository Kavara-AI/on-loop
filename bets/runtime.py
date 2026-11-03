"""A local proof of the bet lifecycle; not the shared production graph."""
import argparse
import contextlib
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def encode(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed


def validate(spec):
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    for key in ("question", "hypothesis", "wrong_question_check", "evidence_spec", "kill_criteria"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            raise ValueError("required nonempty text: " + key)
    candidates = spec.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        raise ValueError("provide at least two candidate names")
    if any(not isinstance(x, str) or not x.strip() for x in candidates):
        raise ValueError("candidate names must be nonempty text")
    if len(set(candidates)) != len(candidates):
        raise ValueError("candidate names must be unique")
    for key in ("budget_microusd", "reservation_microusd"):
        if type(spec.get(key)) is not int or spec[key] < 0:
            raise ValueError(key + " must be a nonnegative integer")
    if spec["reservation_microusd"] > spec["budget_microusd"]:
        raise ValueError("reservation exceeds budget")
    if any(not isinstance(spec.get(key), str) for key in ("starts_at", "ends_at")):
        raise ValueError("start/end must be timezone-qualified text")
    start, end = timestamp(spec["starts_at"]), timestamp(spec["ends_at"])
    if end <= start:
        raise ValueError("end must follow start")
    encode(spec)


def replay(events):
    """Rebuild all current state solely from ordered immutable events."""
    states = {}
    for event in events:
        iri, kind, payload = event["iri"], event["kind"], event["payload"]
        if kind == "opened":
            states[iri] = dict(spec=payload["spec"], status="open", reserved_microusd=0,
                               active=None, evidence=[], prior=payload["prior"], decision=None)
        elif kind == "reserved":
            states[iri]["reserved_microusd"] += payload["amount"]
            states[iri]["active"] = payload["attempt"]
        elif kind == "evidence":
            states[iri]["evidence"].append(payload)
        elif kind == "decided":
            states[iri]["status"] = payload["status"]
            states[iri]["decision"] = payload["reason"]
            states[iri]["active"] = None
        else:
            raise ValueError("unknown event type: " + kind)
    return states


class Store:
    """SQLite is a disposable single-host adapter, not the proposed Postgres tier."""
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, iri TEXT NOT NULL, kind TEXT NOT NULL,
            payload TEXT NOT NULL, recorded_at TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'append-only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'append-only'); END;
        """)

    def close(self):
        self.db.close()

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def events(self):
        return [dict(seq=a, iri=b, kind=c, payload=json.loads(d), recorded_at=e)
                for a, b, c, d, e in self.db.execute("SELECT * FROM events ORDER BY seq")]

    def states(self):
        return replay(self.events())

    def append(self, iri, kind, payload):
        self.db.execute("INSERT INTO events(iri,kind,payload,recorded_at) VALUES (?,?,?,?)",
                        (iri, kind, encode(payload), utcnow().isoformat()))

    def recall(self, query):
        """Explicit lexical recall; semantic graph recall is not implemented."""
        words = set(query.casefold().split())
        return [dict(iri=iri, status=s["status"], question=s["spec"]["question"])
                for iri, s in self.states().items()
                if words.intersection(s["spec"]["question"].casefold().split())]

    def open(self, spec):
        validate(spec)
        with self.transaction():
            prior = self.recall(spec["question"])
            iri = "urn:uuid:" + str(uuid.uuid4())
            self.append(iri, "opened", dict(spec=spec, prior=prior))
        return iri

    def decide(self, iri, status, reason, attempt=None):
        if status not in ("won", "killed", "inconclusive") or not reason.strip():
            raise ValueError("explicit terminal status and reason required")
        with self.transaction():
            state = self.states()[iri]
            if state["status"] != "open":
                raise ValueError("bet already terminal")
            if state["active"] != attempt:
                raise ValueError("active worker owns this bet; reconcile before deciding")
            if status == "won" and not state["evidence"]:
                raise ValueError("a win needs evidence")
            self.append(iri, "decided", dict(status=status, reason=reason))

    def reserve(self, iri, now=None):
        now = now or utcnow()
        with self.transaction():
            state = self.states()[iri]
            spec = state["spec"]
            if state["status"] != "open" or state["active"]:
                raise ValueError("bet is terminal or has an unresolved worker")
            if now < timestamp(spec["starts_at"]):
                raise ValueError("bet has not started")
            if now >= timestamp(spec["ends_at"]):
                self.append(iri, "decided", dict(status="inconclusive", reason="deadline reached"))
                return None
            amount = spec["reservation_microusd"]
            if state["reserved_microusd"] + amount > spec["budget_microusd"]:
                self.append(iri, "decided", dict(status="killed", reason="allocation budget exhausted"))
                return None
            attempt = str(uuid.uuid4())
            self.append(iri, "reserved", dict(attempt=attempt, amount=amount))
            return attempt, state

    def evidence(self, iri, attempt, payload):
        with self.transaction():
            state = self.states()[iri]
            if state["status"] != "open" or state["active"] != attempt:
                raise ValueError("evidence does not own the active attempt")
            self.append(iri, "evidence", payload)


def bounded_command(argv, input_value, seconds):
    """Run explicit argv, never a shell; discard raw output after hashing."""
    if not argv or seconds <= 0:
        raise ValueError("command and positive remaining time required")
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as input_file:
        input_file.write(encode(input_value).encode())
        input_file.seek(0)
        process = subprocess.Popen(argv, stdin=input_file, stdout=output,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            code = -signal.SIGKILL
        finally:
            # Descendants in the process group cannot outlive the local attempt.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        output.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: output.read(65536), b""):
            digest.update(chunk)
    return dict(exit_code=code, stdout_sha256=digest.hexdigest())


def run(store, iri, worker, oracle):
    """One bounded worker/oracle attempt; an abandoned reservation never replays."""
    admitted = store.reserve(iri)
    if admitted is None:
        return store.states()[iri]
    attempt, state = admitted
    remaining = (timestamp(state["spec"]["ends_at"]) - utcnow()).total_seconds()
    deadline = time.monotonic() + max(0, remaining)
    receipt = dict(attempt=attempt)
    try:
        receipt["worker"] = bounded_command(worker, state, deadline - time.monotonic())
        if receipt["worker"]["exit_code"] != 0:
            status, reason = "inconclusive", "worker failed or timed out"
        else:
            receipt["oracle"] = bounded_command(oracle, dict(state=state, receipt=receipt),
                                                   deadline - time.monotonic())
            status = {0: "won", 10: "killed", 20: "inconclusive"}.get(
                receipt["oracle"]["exit_code"], "inconclusive")
            reason = "oracle exit " + str(receipt["oracle"]["exit_code"])
    except (OSError, ValueError) as error:
        # Never log exception text: argv/path details may contain private values.
        receipt["failure_type"] = type(error).__name__
        status, reason = "inconclusive", "local execution failed"
    store.evidence(iri, attempt, receipt)
    store.decide(iri, status, reason, attempt=attempt)
    return store.states()[iri]


def book(states):
    cards = []
    for iri, state in states.items():
        spec = state["spec"]
        fields = dict(Question=spec["question"], Hypothesis=spec["hypothesis"],
                      Status=state["status"], Deadline=spec["ends_at"],
                      Evidence=len(state["evidence"]), Decision=state["decision"] or "pending",
                      Reserved_microUSD=state["reserved_microusd"],
                      Budget_microUSD=spec["budget_microusd"], IRI=iri)
        cards.append("<article>" + "".join("<p><b>" + html.escape(k) + ":</b> " +
                     html.escape(str(v)) + "</p>" for k, v in fields.items()) + "</article>")
    graph = [{"@id": iri, "@type": "https://schema.org/Action",
              "name": state["spec"]["question"], "description": state["spec"]["hypothesis"],
              "actionStatus": state["status"]} for iri, state in states.items()]
    linked_data = encode({"@graph": graph}).replace("<", "\\u003c")
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            '<title>Bets book — local prototype</title><style>body{font:18px system-ui;'
            'max-width:960px;margin:40px auto;padding:20px;background:#101820;color:#eee}'
            'article{border:1px solid #64748b;padding:20px;margin:20px 0}</style>'
            '<h1>Bets book</h1><p>Local prototype · reservations are not provider billing.</p>'
            + "".join(cards) + '<script type="application/ld+json">' + linked_data + '</script></html>')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="private local SQLite file")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("open").add_argument("spec", type=Path)
    commands.add_parser("recall").add_argument("query")
    commands.add_parser("events")
    commands.add_parser("book").add_argument("output", type=Path)
    command = commands.add_parser("decide")
    command.add_argument("iri")
    command.add_argument("status", choices=["won", "killed", "inconclusive"])
    command.add_argument("reason")
    command = commands.add_parser("run")
    command.add_argument("iri")
    command.add_argument("--worker", required=True, type=json.loads, help="explicit JSON argv")
    command.add_argument("--oracle", required=True, type=json.loads, help="explicit JSON argv")
    args = parser.parse_args()
    store = Store(args.db)
    try:
        if args.command == "open":
            print(store.open(json.loads(args.spec.read_text())))
        elif args.command == "recall":
            print(encode(store.recall(args.query)))
        elif args.command == "events":
            print(encode(store.events()))
        elif args.command == "book":
            args.output.write_text(book(store.states()))
        elif args.command == "decide":
            store.decide(args.iri, args.status, args.reason)
        elif args.command == "run":
            for argv in (args.worker, args.oracle):
                if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
                    raise ValueError("commands must be nonempty JSON arrays of strings")
            print(encode(run(store, args.iri, args.worker, args.oracle)))
    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
        print("bets: operation refused (" + type(error).__name__ + ")", file=sys.stderr)
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
