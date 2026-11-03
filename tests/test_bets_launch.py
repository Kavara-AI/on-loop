import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bets.launch import digest_file, load_manifest
from bets.runtime import Store
from test_bets import spec


class LaunchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.worker = self.root / "worker.py"
        self.oracle = self.root / "oracle.py"
        self.marker = self.root / "ran"
        self.worker.write_text("from pathlib import Path; Path(" + repr(str(self.marker)) + ").touch()")
        self.oracle.write_text("from pathlib import Path; assert Path(" + repr(str(self.marker)) + ").exists()")
        python = str(Path(sys.executable).resolve())
        self.manifest = dict(worker=[python, str(self.worker)], oracle=[python, str(self.oracle)],
                             worker_entrypoint=str(self.worker), oracle_entrypoint=str(self.oracle),
                             run_owner="fixture owner", resource_id="local fixture only",
                             authority_ref="test permission", spend_control_ref="no paid calls",
                             pins=[dict(path=str(x), sha256=digest_file(x))
                                   for x in (Path(python), self.worker, self.oracle)])
        self.path = self.root / "manifest.json"
        self.write_manifest()
        self.db = self.root / "bets.db"
        self.store = Store(str(self.db))
        self.iri = self.store.open(spec(launch_manifest_sha256=self.sha))

    def write_manifest(self):
        self.path.write_text(json.dumps(self.manifest))
        self.sha = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def command(self, *extra, digest=None, iri=None):
        return subprocess.run([sys.executable, "-m", "bets.launch", "--manifest", str(self.path),
                               "--manifest-sha256", digest or self.sha, "--db", str(self.db),
                               "--iri", iri or self.iri, *extra], capture_output=True, text=True)

    def test_check_never_dispatches_or_reserves(self):
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "CHECKED_NOT_RUN")
        self.assertFalse(self.marker.exists())
        self.assertEqual(len(self.store.events()), 1)

    def test_execute_is_bound_to_existing_bet_and_refuses_replay(self):
        result = self.command("--execute")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "won")
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.command("--execute").returncode, 1)
        self.assertEqual(len(self.store.events()), 4)

    def test_changed_model_or_input_pin_prevents_dispatch(self):
        self.worker.write_text("raise SystemExit('changed')")
        self.assertEqual(self.command("--execute").returncode, 1)
        self.assertFalse(self.marker.exists())
        self.assertEqual(len(self.store.events()), 1)

    def test_manifest_change_requires_independent_binding_update(self):
        old = self.sha
        self.manifest["resource_id"] = "another host"
        self.write_manifest()
        self.assertEqual(self.command(digest=old).returncode, 1)
        self.assertEqual(self.command().returncode, 1)  # bet still binds the original

    def test_worker_cannot_replace_pinned_oracle_and_claim_win(self):
        self.worker.write_text("from pathlib import Path; Path(" + repr(str(self.oracle)) + ").write_text('pass')")
        self.manifest["pins"][1]["sha256"] = digest_file(self.worker)
        self.write_manifest()
        iri = self.store.open(spec(launch_manifest_sha256=self.sha))
        result = self.command("--execute", iri=iri)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "inconclusive")
        self.assertNotIn("oracle", self.store.states()[iri]["evidence"][0])

    def test_missing_run_authority_or_spend_reference_is_refused(self):
        for field in ("run_owner", "resource_id", "authority_ref", "spend_control_ref"):
            with self.subTest(field=field):
                value = self.manifest.pop(field)
                self.write_manifest()
                with self.assertRaises(ValueError):
                    load_manifest(self.path, self.sha)
                self.manifest[field] = value

    def test_interpreter_pin_alone_does_not_bind_script(self):
        self.manifest["pins"] = self.manifest["pins"][:1]
        self.write_manifest()
        with self.assertRaises(ValueError):
            load_manifest(self.path, self.sha)

    def test_interpreter_cannot_be_declared_a_direct_wrapper_with_extra_args(self):
        self.manifest["worker_entrypoint"] = self.manifest["worker"][0]
        self.manifest["oracle_entrypoint"] = self.manifest["oracle"][0]
        self.manifest["pins"] = self.manifest["pins"][:1]
        self.write_manifest()
        with self.assertRaises(ValueError):
            load_manifest(self.path, self.sha)

    def test_symlink_or_nonregular_file_is_not_a_valid_pin(self):
        link = self.root / "link"
        link.symlink_to(self.worker)
        with self.assertRaises(ValueError):
            digest_file(link)
        with self.assertRaises(ValueError):
            digest_file(self.root)


if __name__ == "__main__":
    unittest.main()
