#!/usr/bin/env python3
"""Derive frozen pilot expectations from human-reviewed reference scripts.

The only admissible value source is `benchmarks/pilot_reference/*.py`, executed
independently of any candidate. This generator refuses to read `attempt_*.py`,
`final.py`, or any other artifact under the execution output tree (FR-007d).

    python -m benchmarks.derive_pilot_expectations \
        --suite benchmarks/benchmark_prompts_pilot10.json \
        --out benchmarks/pilot_expectations.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grass_agent.config import ExecutionConfig  # noqa: E402
from grass_agent.executor import Executor  # noqa: E402
from grass_agent.semantic_probe import (  # noqa: E402
    classify_geometry,
    feature_count,
    parse_univar,
    parse_v_info_columns,
    parse_v_info_topology,
)

REFERENCE_DIR = REPO_ROOT / "benchmarks" / "pilot_reference"

WRAPPER = r'''
import json
import runpy
import subprocess
import sys

script_path, spec_path, out_path = sys.argv[1:4]
with open(spec_path, encoding="utf-8") as handle:
    spec = json.load(handle)

runpy.run_path(script_path, run_name="__main__")

payload = {}
for output in spec["outputs"]:
    name = output["name"]
    kind = output["type"]
    entry = {"type": kind}
    if kind == "raster":
        try:
            completed = subprocess.run(
                ["r.univar", "-g", "-r", "map={0}".format(name)],
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.SubprocessError as exc:
            entry.update(returncode=-1, stdout="", error=str(exc))
        else:
            entry.update(
                returncode=completed.returncode,
                stdout=completed.stdout or "",
                stderr=completed.stderr or "",
            )
    else:
        try:
            topology = subprocess.run(
                ["v.info", "-t", "map={0}".format(name)],
                capture_output=True, text=True, timeout=120,
            )
            columns = subprocess.run(
                ["v.info", "-c", "map={0}".format(name)],
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.SubprocessError as exc:
            entry.update(returncode=-1, stdout="", error=str(exc))
        else:
            entry.update(
                topology_returncode=topology.returncode,
                topology_stdout=topology.stdout or "",
                columns_returncode=columns.returncode,
                columns_stdout=columns.stdout or "",
            )
    payload[name] = entry

with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
'''


def _guard_reference(script: Path) -> Path:
    """Refuse any value source that is candidate output."""
    resolved = script.resolve()
    if resolved.name.startswith("attempt_") or resolved.name == "final.py":
        raise SystemExit(
            f"refusing candidate artifact as a value source: {resolved}"
        )
    try:
        resolved.relative_to(REFERENCE_DIR.resolve())
    except ValueError:
        raise SystemExit(
            f"reference scripts must live under {REFERENCE_DIR}: {resolved}"
        ) from None
    return resolved


def grass_version(grass_bin: str = "grass") -> str:
    completed = subprocess.run(
        [grass_bin, "--version"], capture_output=True, text=True, timeout=30
    )
    first = (completed.stdout or completed.stderr or "").strip().splitlines()
    if not first:
        raise SystemExit("could not determine the GRASS version")
    # "GRASS 8.5.0 (...)" -> "8.5.0"
    parts = first[0].split()
    return parts[1] if len(parts) > 1 else first[0]


def run_reference(
    script: Path,
    outputs: list[dict],
    dataset_project: Path,
    grass_bin: str,
    workdir: Path,
) -> dict:
    spec_path = workdir / "outputs.json"
    out_path = workdir / "raw.json"
    wrapper_path = workdir / "derive_case.py"
    spec_path.write_text(json.dumps({"outputs": outputs}), encoding="utf-8")
    wrapper_path.write_text(WRAPPER, encoding="utf-8")

    completed = subprocess.run(
        [
            grass_bin,
            "--tmp-mapset",
            f"{dataset_project}/",
            "--exec",
            sys.executable,
            str(wrapper_path),
            str(script),
            str(spec_path),
            str(out_path),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=str(workdir),
    )
    if completed.returncode != 0 or not out_path.is_file():
        raise SystemExit(
            f"reference execution failed for {script.name}: "
            f"{completed.stderr.strip()[-800:]}"
        )
    return json.loads(out_path.read_text(encoding="utf-8"))


def normalize(raw: dict) -> dict:
    output: dict = {}
    for name, entry in raw.items():
        kind = entry.get("type")
        if kind == "raster":
            if entry.get("returncode") != 0:
                raise SystemExit(f"r.univar failed for {name}: {entry}")
            try:
                stats = parse_univar(entry.get("stdout", ""))
            except (ValueError, TypeError) as exc:
                raise SystemExit(f"could not parse r.univar for {name}: {exc}")
            output[name] = {
                "type": "raster",
                "n": stats["n"],
                "min": stats["min"],
                "max": stats["max"],
                "mean": stats["mean"],
            }
        else:
            if entry.get("topology_returncode") != 0:
                raise SystemExit(f"v.info -t failed for {name}: {entry}")
            topology = parse_v_info_topology(entry.get("topology_stdout", ""))
            geometry = classify_geometry(topology)
            columns: list[str] = []
            if entry.get("columns_returncode") == 0:
                columns = parse_v_info_columns(entry.get("columns_stdout", ""))
            output[name] = {
                "type": "vector",
                "geometry": geometry,
                "feature_count": feature_count(topology, geometry),
                "columns": columns,
            }
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive frozen pilot expectations from reference scripts."
    )
    parser.add_argument(
        "--suite",
        default="benchmarks/benchmark_prompts_pilot10.json",
        help="Pilot suite definition",
    )
    parser.add_argument(
        "--out",
        default="benchmarks/pilot_expectations.json",
        help="Destination expectations file",
    )
    parser.add_argument(
        "--dataset", default=None, help="GRASS project (auto-detected by default)"
    )
    args = parser.parse_args(argv)

    suite_path = Path(args.suite)
    if not suite_path.is_absolute():
        suite_path = REPO_ROOT / suite_path
    suite = json.loads(suite_path.read_text(encoding="utf-8"))

    if args.dataset:
        config = ExecutionConfig(dataset_project=args.dataset)
    else:
        config = ExecutionConfig.detect_dataset()
    dataset_project = config.dataset_path
    if not ExecutionConfig.is_valid_project(dataset_project):
        raise SystemExit(f"{dataset_project} is not a usable GRASS project")

    cases: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="pilot_expectations_") as tmp:
        root = Path(tmp)
        for case in suite.get("test_cases", []):
            case_id = case["id"]
            script = _guard_reference(REFERENCE_DIR / f"{case_id}.py")
            workdir = root / case_id
            workdir.mkdir(parents=True, exist_ok=True)
            print(f"[{case_id}] executing reference script ...", flush=True)
            raw = run_reference(
                script,
                list(case.get("outputs") or []),
                dataset_project,
                config.grass_bin,
                workdir,
            )
            cases[case_id] = {
                "reference_script": str(script.relative_to(REPO_ROOT)),
                "reference_script_sha256": hashlib.sha256(
                    script.read_bytes()
                ).hexdigest(),
                "outputs": normalize(raw),
            }

    payload = {
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "benchmarks/derive_pilot_expectations.py",
        "grass_version": grass_version(config.grass_bin),
        "dataset": {
            "project": str(dataset_project),
            "permanent_hash": Executor.permanent_hash(dataset_project),
        },
        "cases": cases,
    }

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {out_path} ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
