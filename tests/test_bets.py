import datetime as dt
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from bets.runtime import Store, book, replay, run, utcnow, validate


def spec(**changes):
    value = dict(question="Does candidate B beat A?", hypothesis="B reduces error",
                 wrong_question_check="Perhaps latency matters more",
                 candidates=["A", "B"], evidence_spec="Independent oracle evaluates both",
                 kill_criteria="No improvement or budget exhausted",
                 budget_microusd=100, reservation_microusd=100,
                 starts_at=(utcnow() - dt.timedelta(minutes=1)).isoformat(),
                 ends_at=(utcnow() + dt.timedelta(minutes=1)).isoformat())
    return dict(value, **changes)


class BetsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "bets.db")
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_worker_and_independent_oracle_finish_with_replayable_evidence(self):
        iri = self.store.open(spec())
        state = run(self.store, iri, [sys.executable, "-c", "print('measurement')"],
                    [sys.executable, "-c", "import json,sys; x=json.load(sys.stdin); assert x['receipt']['worker']['exit_code']==0"])
        self.assertEqual(state["status"], "won")
        self.assertEqual(state["reserved_microusd"], 100)
        self.assertEqual(self.store.states(), replay(self.store.events()))
        self.assertNotIn("measurement", json.dumps(self.store.events()))
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(state, self.store.states()[iri])

    def test_recall_includes_previously_killed_bet_before_open(self):
        first = self.store.open(spec())
        self.store.decide(first, "killed", "Question was wrong")
        second = self.store.open(spec())
        self.assertEqual(self.store.states()[second]["prior"][0]["iri"], first)
        self.assertEqual(self.store.states()[second]["prior"][0]["status"], "killed")

    def test_two_connections_cannot_reserve_same_bet(self):
        iri = self.store.open(spec())
        self.store.reserve(iri)
        other = Store(self.path)
        try:
            with self.assertRaisesRegex(ValueError, "unresolved"):
                other.reserve(iri)
        finally:
            other.close()
        self.assertEqual(self.store.states()[iri]["reserved_microusd"], 100)

    def test_abandoned_worker_is_not_retried_or_released_after_reopen(self):
        iri = self.store.open(spec())
        self.store.reserve(iri)
        self.store.close()
        self.store = Store(self.path)
        with self.assertRaises(ValueError):
            self.store.reserve(iri)
        with self.assertRaises(ValueError):
            self.store.decide(iri, "inconclusive", "unsafe takeover")

    def test_deadline_is_terminal_before_any_worker_runs(self):
        iri = self.store.open(spec())
        self.assertIsNone(self.store.reserve(iri, now=utcnow() + dt.timedelta(hours=1)))
        self.assertEqual(self.store.states()[iri]["status"], "inconclusive")
        self.assertEqual(self.store.states()[iri]["reserved_microusd"], 0)

    def test_before_start_does_not_mutate_state(self):
        iri = self.store.open(spec())
        with self.assertRaises(ValueError):
            self.store.reserve(iri, now=utcnow() - dt.timedelta(hours=1))
        self.assertEqual(len(self.store.events()), 1)

    def test_terminal_bet_never_dispatches_again(self):
        iri = self.store.open(spec())
        self.store.decide(iri, "inconclusive", "closed")
        with self.assertRaises(ValueError):
            self.store.reserve(iri)

    def test_cli_opens_and_renders_book(self):
        source = Path(self.tmp.name) / "spec.json"
        source.write_text(json.dumps(spec()))
        prefix = [sys.executable, "-m", "bets.runtime", "--db", self.path]
        opened = subprocess.run(prefix + ["open", str(source)], check=True, capture_output=True, text=True)
        self.assertTrue(opened.stdout.strip().startswith("urn:uuid:"))
        output = Path(self.tmp.name) / "book.html"
        subprocess.run(prefix + ["book", str(output)], check=True)
        self.assertIn("Does candidate B", output.read_text())

    def test_transaction_rolls_back_failed_event(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.append("urn:uuid:example", "invalid", {})
                raise RuntimeError("abort")
        self.assertEqual(self.store.events(), [])

    def test_worker_failure_does_not_run_oracle(self):
        iri = self.store.open(spec())
        marker = Path(self.tmp.name) / "oracle-called"
        state = run(self.store, iri, [sys.executable, "-c", "raise SystemExit(1)"],
                    [sys.executable, "-c", "from pathlib import Path; Path(" + repr(str(marker)) + ").touch()"])
        self.assertEqual(state["status"], "inconclusive")
        self.assertFalse(marker.exists())

    def test_timeout_terminates_worker(self):
        iri = self.store.open(spec(ends_at=(utcnow() + dt.timedelta(seconds=.2)).isoformat()))
        state = run(self.store, iri, [sys.executable, "-c", "import time; time.sleep(10)"],
                    [sys.executable, "-c", "pass"])
        self.assertEqual(state["status"], "inconclusive")
        self.assertEqual(state["evidence"][0]["worker"]["exit_code"], -9)

    def test_oracle_controls_decision_and_invalid_exit_is_inconclusive(self):
        for code, expected in [(10, "killed"), (20, "inconclusive"), (3, "inconclusive")]:
            with self.subTest(code=code):
                iri = self.store.open(spec())
                state = run(self.store, iri, [sys.executable, "-c", "pass"],
                            [sys.executable, "-c", "raise SystemExit(" + str(code) + ")"])
                self.assertEqual(state["status"], expected)

    def test_no_win_without_evidence_and_no_reopening(self):
        iri = self.store.open(spec())
        with self.assertRaises(ValueError):
            self.store.decide(iri, "won", "trust me")
        self.store.decide(iri, "killed", "wrong bet")
        with self.assertRaises(ValueError):
            self.store.decide(iri, "won", "change history")

    def test_database_enforces_append_only_events(self):
        self.store.open(spec())
        for query in ("DELETE FROM events", "UPDATE events SET kind='decided'"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.store.db.execute(query)

    def test_invalid_budget_candidates_and_time_are_refused(self):
        for changes in (dict(budget_microusd=True), dict(reservation_microusd=-1),
                        dict(budget_microusd=1), dict(candidates=["A"]),
                        dict(candidates=["A", "A"]), dict(starts_at="2026-01-01"),
                        dict(wrong_question_check=""), dict(ends_at=None)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(spec(**changes))
        self.assertEqual(self.store.events(), [])

    def test_book_escapes_untrusted_text(self):
        iri = self.store.open(spec(question="<script>alert('x')</script>"))
        output = book(self.store.states())
        self.assertIn("&lt;script&gt;", output)
        self.assertNotIn("<script>alert", output)
        self.assertIn(iri, output)

    def test_missing_executable_retains_accounting_and_failure_receipt(self):
        iri = self.store.open(spec())
        state = run(self.store, iri, ["/does/not/exist"], [sys.executable, "-c", "pass"])
        self.assertEqual(state["status"], "inconclusive")
        self.assertEqual(state["reserved_microusd"], 100)
        self.assertEqual(state["evidence"][0]["failure_type"], "FileNotFoundError")


if __name__ == "__main__":
    unittest.main()
