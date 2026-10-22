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

This file is a standalone script rather than an importable module because it is
copied into the GRASS session and executed there, outside the project package.

Usage:
    python3 inner_wrapper.py <status.json> <script.py> [args...]

Also note: `faulthandler.register(11, ...)` does not work -- it raises
`RuntimeError: signal 11 cannot be registered, use enable() instead`. Only the
fork gives a programmatic signal number.
"""

import json
import os
import signal
import sys


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: inner_wrapper.py <status.json> <script.py> [args...]", file=sys.stderr)
        return 2

    status_path, script_path = sys.argv[1], sys.argv[2]
    script_args = sys.argv[3:]

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
            result["signal_name"] = f"SIG{signum}"
        result["status"] = "crashed"
    elif os.WIFEXITED(raw_status):
        code = os.WEXITSTATUS(raw_status)
        result["returncode"] = code
        result["exit_code"] = code
        result["status"] = "exited"

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