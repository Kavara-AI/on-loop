import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from bets.runtime import bounded_command


class SupervisorTest(unittest.TestCase):
    def test_worker_and_grandchild_stop_even_if_driver_is_sigkilled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ready = root / "ready.json"
            late = root / "late"
            child_late = root / "child-late"
            child_code = "import time; from pathlib import Path; time.sleep(3); Path(" + repr(str(child_late)) + ").touch()"
            worker = [sys.executable, "-c",
                      "import os,json,time,subprocess,sys; from pathlib import Path; "
                      "child=subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "]); "
                      "Path(" + repr(str(ready)) + ").write_text(json.dumps({'worker':os.getpid(),'child':child.pid})); "
                      "time.sleep(3); Path(" + repr(str(late)) + ").touch()"]
            code = "from bets.runtime import bounded_command; bounded_command(" + repr(worker) + ",{},2)"
            driver = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            pids = {}
            try:
                until = time.monotonic() + 1.5
                while not ready.exists() and time.monotonic() < until:
                    time.sleep(.01)
                self.assertTrue(ready.exists(), "worker readiness not reached before kill")
                pids = json.loads(ready.read_text())
                driver.kill()
                self.assertEqual(driver.wait(timeout=2), -signal.SIGKILL)
                time.sleep(3.3)
                self.assertFalse(late.exists(), "worker escaped original deadline")
                self.assertFalse(child_late.exists(), "grandchild escaped original deadline")
                # Supervisor reaps its direct worker; no live worker may remain.
                with self.assertRaises(ProcessLookupError):
                    os.kill(pids["worker"], 0)
            finally:
                if driver.poll() is None:
                    driver.kill()
                    driver.wait()
                # Only our newly created worker group is a cleanup target.
                # A child's ppid can be a host subreaper, not our supervisor.
                for key in ("worker",):
                    if key in pids:
                        try:
                            os.killpg(pids[key], signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_supervisor_preserves_payload_and_receipt(self):
        result = bounded_command([sys.executable, "-c", "import json,sys; x=json.load(sys.stdin); assert x=={'x':1}; print('ok')"], {"x": 1}, 2)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(len(result["stdout_sha256"]), 64)

    def test_supervisor_returns_timeout_without_driver_failure(self):
        result = bounded_command([sys.executable, "-c", "import time; time.sleep(20)"], {}, .2)
        self.assertEqual(result["exit_code"], -signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
