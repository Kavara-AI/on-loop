"""Executable local lifecycle demonstration; no model/API/paid calls."""
import datetime as dt
from pathlib import Path
import sys
import tempfile

from bets.runtime import Store, book, replay, run, utcnow


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("bets-book.html")
    with tempfile.TemporaryDirectory() as directory:
        store = Store(str(Path(directory) / "events.db"))
        spec = dict(question="Does sorting B preserve the same result as sorting A?",
                    hypothesis="Both candidates return identical sorted values",
                    wrong_question_check="This only proves the lifecycle, not useful agent research",
                    candidates=["sorted", "list.sort"], evidence_spec="Independent comparison of both results",
                    kill_criteria="Different output, failed command, or deadline",
                    budget_microusd=0, reservation_microusd=0,
                    starts_at=utcnow().isoformat(),
                    ends_at=(utcnow() + dt.timedelta(minutes=1)).isoformat())
        iri = store.open(spec)
        artifact = str(Path(directory) / "candidates.json")
        worker = [sys.executable, "-c",
                  "import json,sys; from pathlib import Path; a=[3,1,2]; b=a.copy(); b.sort(); "
                  "data=json.dumps({'A':sorted(a),'B':b}).encode(); "
                  "Path(sys.argv[1]).write_bytes(data); sys.stdout.buffer.write(data)", artifact]
        oracle = [sys.executable, "-c",
                  "import hashlib,json,sys; from pathlib import Path; "
                  "receipt=json.load(sys.stdin); data=Path(sys.argv[1]).read_bytes(); "
                  "assert hashlib.sha256(data).hexdigest()==receipt['receipt']['worker']['stdout_sha256']; "
                  "results=json.loads(data); assert results['A']==results['B']==[1,2,3]", artifact]
        result = run(store, iri, worker, oracle)
        if replay(store.events()) != store.states() or result["status"] != "won":
            raise RuntimeError("demo failed")
        output.write_text(book(store.states()))
        print("Local lifecycle: won; one worker, independent oracle, evidence and replay verified.")
        store.close()


if __name__ == "__main__":
    main()
