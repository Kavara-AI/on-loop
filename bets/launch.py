"""Bind an existing bet to operator-pinned local worker/oracle commands."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from .runtime import Store, encode, run


def digest_file(path):
    """Hash a regular file without following links; require canonical paths."""
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("pins need absolute canonical paths")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("pins must refer to regular files")
    with os.fdopen(fd, "rb") as stream:
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path, expected):
    """The separately supplied digest is the operator's exact command binding."""
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("manifest digest mismatch")
    manifest = json.loads(data)
    for field in ("run_owner", "resource_id", "authority_ref", "spend_control_ref"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError("missing explicit local run binding")
    pins = manifest.get("pins")
    if not isinstance(pins, list) or not pins:
        raise ValueError("input/code pins required")
    seen = set()
    for pin in pins:
        if pin["path"] in seen or digest_file(pin["path"]) != pin["sha256"]:
            raise ValueError("duplicate or changed pin")
        seen.add(pin["path"])
    for field in ("worker", "oracle"):
        argv = manifest.get(field)
        if not isinstance(argv, list) or not argv or any(not isinstance(x, str) for x in argv):
            raise ValueError("explicit argv required")
        if argv[0] not in seen or not os.access(argv[0], os.X_OK):
            raise ValueError("command executable must be pinned")
        entrypoint = manifest.get(field + "_entrypoint")
        if entrypoint not in seen:
            raise ValueError("command entrypoint must be pinned")
        if argv[0] != entrypoint and (len(argv) < 2 or argv[1] != entrypoint):
            raise ValueError("use a pinned executable wrapper or interpreter plus pinned script")
    if manifest["worker"] == manifest["oracle"]:
        raise ValueError("worker and oracle commands must be separate")
    return manifest


def verify_bet(store, iri, digest):
    state = store.states()[iri]
    if state["spec"].get("launch_manifest_sha256") != digest:
        raise ValueError("existing bet does not bind this manifest")
    if state["status"] != "open" or state["active"]:
        raise ValueError("bet terminal or unresolved attempt exists")
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--iri", required=True)
    parser.add_argument("--execute", action="store_true", help="explicitly dispatch; default is check only")
    args = parser.parse_args()
    store = None
    try:
        manifest = load_manifest(args.manifest, args.manifest_sha256)
        # Missing DB must not create an empty journal or a replacement bet.
        if not Path(args.db).is_file():
            raise ValueError("existing bet database required")
        store = Store(args.db)
        verify_bet(store, args.iri, args.manifest_sha256)
        if args.execute:
            result = run(store, args.iri, manifest["worker"], manifest["oracle"],
                         before_oracle=lambda: load_manifest(args.manifest, args.manifest_sha256))
            print(encode(dict(status=result["status"], manifest_sha256=args.manifest_sha256)))
        else:
            print(encode(dict(status="CHECKED_NOT_RUN", manifest_sha256=args.manifest_sha256)))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print("launch: binding refused (" + type(error).__name__ + ")", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
