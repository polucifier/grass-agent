#!/usr/bin/env python3
"""Deprecated alias for benchmarks.run_gate1."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import benchmarks.run_gate1 as _run_gate1  # noqa: E402

main = _run_gate1.main


def __getattr__(name):
    return getattr(_run_gate1, name)


if __name__ == "__main__":
    print(
        "warning: benchmarks/run_eval.py is deprecated; "
        "use benchmarks/run_gate1.py or python -m benchmarks.run_gate1",
        file=sys.stderr,
    )
    sys.exit(main())
