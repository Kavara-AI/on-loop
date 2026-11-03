"""Own a local worker's deadline independently of the calling driver.

This process is not a security boundary or a provider spending controller.
"""
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import time


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def supervise(input_fd, output_fd, result_fd):
    with os.fdopen(input_fd, "r") as source:
        config = json.load(source)
    deadline = config["deadline_monotonic"]
    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError("finite deadline required")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        code = -signal.SIGKILL
    else:
        # The worker sees only the bet payload, not supervisor control fields.
        import tempfile
        with tempfile.TemporaryFile() as payload:
            payload.write(json.dumps(config["payload"], allow_nan=False).encode())
            payload.seek(0)
            try:
                process = subprocess.Popen(config["argv"], stdin=payload, stdout=output_fd,
                                           stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as error:
                with os.fdopen(result_fd, "w") as result:
                    json.dump(dict(failure_type=type(error).__name__), result)
                return
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
                code = process.returncode
            except subprocess.TimeoutExpired:
                code = -signal.SIGKILL
            finally:
                kill_group(process)
                process.wait()
    with os.fdopen(output_fd, "rb") as output:
        output.seek(0)
        digest = hashlib.sha256()
        for chunk in iter(lambda: output.read(65536), b""):
            digest.update(chunk)
    with os.fdopen(result_fd, "w") as result:
        json.dump(dict(exit_code=code, stdout_sha256=digest.hexdigest()), result)
        result.flush()


if __name__ == "__main__":
    try:
        supervise(*(int(x) for x in sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError):
        # No argv, private path or payload diagnostics on public stderr.
        sys.exit(1)
