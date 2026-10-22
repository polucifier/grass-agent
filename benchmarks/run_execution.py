#!/usr/bin/env python3
"""Deprecated alias for benchmarks.run_gate2."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import benchmarks.run_gate2 as _run_gate2  # noqa: E402

main = _run_gate2.main


def __getattr__(name):
    return getattr(_run_gate2, name)


if __name__ == "__main__":
    print(
        "warning: benchmarks/run_execution.py is deprecated; "
        "use benchmarks/run_gate2.py or python -m benchmarks.run_gate2",
        file=sys.stderr,
    )
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
