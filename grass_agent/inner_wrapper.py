#!/usr/bin/env python3
"""Fork-and-waitpid status reporter for GRASS child execution.

Why this exists (research R5, decision D3). `/usr/bin/grass --exec` reports the
child's exit status via `sys.exit(proc.wait())`, and Python maps a negative
status to `256 - n`. The result is that a child SIGSEGV and a child
`sys.exit(245)` both surface as exit code 245 -- byte-identical, and
indistinguishable. `returncode < 0` is unreachable through the wrapper. No
exit-code heuristic can recover the signal.

The fix is a parent that outlives the crash. This wrapper forks, execs the real
script in the child, and `waitpid`s from the parent. The parent is an ordinary
Python process holding GRASS's injected `PYTHONPATH`, so the child can `import
grass.tools` exactly as if it had been exec'd directly.

Gate 3 adds a read-only layer around that fork: the parent snapshots the
current mapset before the child, snapshots it again after a zero-exit child,
and (when a semantic spec is present) runs the in-session probe. Nothing here
can change the child's status or signal semantics.

This file is a standalone script rather than an importable module because it is
copied into the GRASS session and executed there, outside the project package.

Usage:
    python3 inner_wrapper.py <status.json> <script.py> [args...]

Environment (set by Executor.execute):
    GRASS_AGENT_MAPS_OUT          maps.json destination (optional)
    GRASS_AGENT_SEMANTIC_SPEC     semantic_spec.json (optional)
    GRASS_AGENT_SEMANTIC_OUT      semantic.json destination (optional)
    GRASS_AGENT_CASE_ID           case id echoed into both files (optional)

Also note: `faulthandler.register(11, ...)` does not work -- it raises
`RuntimeError: signal 11 cannot be registered, use enable() instead`. Only the
fork gives a programmatic signal number.
"""

import json
import os
import signal
import subprocess
import sys


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _snapshot_maps(timeout_s):
    """Snapshot rasters and vectors in the current scratch mapset only."""
    snapshot = {"raster": [], "vector": []}
    for kind in ("raster", "vector"):
        try:
            completed = subprocess.run(
                ["g.list", "type={0}".format(kind), "mapset=."],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except (OSError, subprocess.SubprocessError):
            return snapshot, "query_failed"
        if completed.returncode != 0:
            return snapshot, "query_failed"
        snapshot[kind] = sorted(
            line.strip()
            for line in (completed.stdout or "").splitlines()
            if line.strip()
        )
    return snapshot, None


def _new_maps(before, after):
    return {
        kind: sorted(set(after.get(kind) or []) - set(before.get(kind) or []))
        for kind in ("raster", "vector")
    }


def _write_json(path, payload):
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _probe(spec_path, before, after, maps_out, semantic_out, case_id):
    """Run the read-only probe; never let a probe problem mask the child."""
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)

    # The probe is copied next to this wrapper by Executor.execute().
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import semantic_probe  # noqa: PLC0415 - resolved from the workdir at runtime

    return semantic_probe.run_probe(
        spec,
        before,
        after,
        maps_out=maps_out,
        semantic_out=semantic_out,
    )


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: inner_wrapper.py <status.json> <script.py> [args...]", file=sys.stderr)
        return 2

    status_path, script_path = sys.argv[1], sys.argv[2]
    script_args = sys.argv[3:]

    maps_out = os.environ.get("GRASS_AGENT_MAPS_OUT") or ""
    semantic_out = os.environ.get("GRASS_AGENT_SEMANTIC_OUT") or ""
    semantic_spec = os.environ.get("GRASS_AGENT_SEMANTIC_SPEC") or ""
    case_id = os.environ.get("GRASS_AGENT_CASE_ID", "")
    snapshot_timeout = _env_int("GRASS_AGENT_SNAPSHOT_TIMEOUT", 30)

    before, snapshot_error = _snapshot_maps(snapshot_timeout)

    pid = os.fork()
    if pid == 0:
        # Child: become the target script.
        try:
            sys.argv = [script_path] + script_args
            sys.stdout.flush()
            sys.stderr.flush()
            os.execv(sys.executable, [sys.executable, script_path] + script_args)
        except BaseException:  # noqa: BLE001 - must never return to the parent
            os._exit(127)

    # Parent: outlives any crash in the child.
    _, raw_status = os.waitpid(pid, 0)

    result = {"returncode": None, "status": "unknown", "signal": None, "signal_name": None}
    if os.WIFSIGNALED(raw_status):
        signum = os.WTERMSIG(raw_status)
        result["returncode"] = -signum
        result["signal"] = signum
        try:
            result["signal_name"] = signal.Signals(signum).name
        except ValueError:
            result["signal_name"] = "SIG{0}".format(signum)
        result["status"] = "crashed"
    elif os.WIFEXITED(raw_status):
        code = os.WEXITSTATUS(raw_status)
        result["returncode"] = code
        result["exit_code"] = code
        result["status"] = "exited"

    # ---- map snapshot and read-only probe (never changes the child's status)
    exited_ok = result["status"] == "exited" and result.get("exit_code") == 0
    after = before
    maps_error = snapshot_error
    if exited_ok:
        after, maps_error = _snapshot_maps(snapshot_timeout)
    discovered = _new_maps(before, after) if exited_ok else {"raster": [], "vector": []}

    if maps_out:
        try:
            _write_json(
                maps_out,
                {
                    "schema_version": 1,
                    "case_id": case_id,
                    "before": {
                        "raster": before.get("raster") or [],
                        "vector": before.get("vector") or [],
                    },
                    "after": {
                        "raster": after.get("raster") or [],
                        "vector": after.get("vector") or [],
                    },
                    "new_maps": discovered,
                    "error": maps_error,
                },
            )
        except OSError:
            pass

    if exited_ok and semantic_spec:
        try:
            _probe(
                semantic_spec, before, after, maps_out, semantic_out, case_id
            )
        except BaseException:  # noqa: BLE001 - a probe fault is a semantic failure
            if semantic_out:
                try:
                    _write_json(
                        semantic_out,
                        {
                            "schema_version": 1,
                            "case_id": case_id,
                            "evaluated": True,
                            "passed": False,
                            "new_maps": discovered,
                            "outputs": [],
                            "error": "parse_error",
                            "elapsed_s": 0.0,
                        },
                    )
                except OSError:
                    pass
    elif semantic_out:
        try:
            _write_json(
                semantic_out,
                {
                    "schema_version": 1,
                    "case_id": case_id,
                    "evaluated": False,
                    "passed": False,
                    "new_maps": discovered,
                    "outputs": [],
                    "error": None,
                    "elapsed_s": 0.0,
                },
            )
        except OSError:
            pass

    # Atomic write: the parent may be killed between the two operations.
    tmp_path = status_path + ".part"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, status_path)

    # Re-raise so the outer `grass --exec` wrapper also observes the signal.
    if result["signal"] is not None:
        signal.signal(result["signal"], signal.SIG_DFL)
        os.kill(os.getpid(), result["signal"])

    return (result["returncode"] or 0) & 0xFF


if __name__ == "__main__":
    sys.exit(main())
