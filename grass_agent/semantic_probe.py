#!/usr/bin/env python3
"""Read-only semantic probe executed inside the candidate's GRASS session.

Deliberately standalone: `inner_wrapper.py` copies this file next to itself and
imports it, so it must not import the `grass_agent` package. It never writes a
map, never opens `PERMANENT` for writing, and never derives an expected value
from candidate output.

Queries (contracts/semantic-result.md):

    g.list type=raster mapset=.
    g.list type=vector mapset=.
    r.univar -g -r map=<name>
    v.info -t map=<name>
    v.info -c map=<name>
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

ERROR_PROBE_TIMEOUT = "probe_timeout"
ERROR_QUERY_TIMEOUT = "query_timeout"
ERROR_QUERY_FAILED = "query_failed"
ERROR_MISSING_OUTPUT = "missing_output"
ERROR_WRONG_TYPE = "wrong_type"
ERROR_NO_VALUES = "no_values"
ERROR_NON_FINITE = "non_finite"
ERROR_PARSE_ERROR = "parse_error"

DEFAULT_QUERY_TIMEOUT_S = 30
DEFAULT_PROBE_TIMEOUT_S = 60


@dataclass
class QueryResult:
    stdout: str = ""
    returncode: int = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.returncode == 0


def default_runner(args: list[str], timeout_s: float) -> QueryResult:
    """Run one read-only GRASS module in the current session.

    `subprocess` is used rather than `grass.script` so parsing is a pure
    function of stable text output; this is harness infrastructure, never
    generated code, so the `grass.tools` mandate does not apply.
    """
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=dict(os.environ),
        )
        return QueryResult(
            stdout=completed.stdout or "",
            returncode=completed.returncode,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        return QueryResult(stdout="", returncode=-1, timed_out=True)
    except (OSError, subprocess.SubprocessError):
        return QueryResult(stdout="", returncode=-1, timed_out=False)


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def parse_univar(text: str) -> dict:
    """Parse `r.univar -g` output into n/min/max/mean floats."""
    values = parse_key_values(text)
    parsed: dict = {}
    for key in ("n", "min", "max","mean"):
        if key not in values:
            raise ValueError(f"missing {key}")
        parsed[key] = float(values[key])
    parsed["n"] = int(parsed["n"])
    return parsed


def parse_v_info_topology(text: str) -> dict[str, int]:
    values = parse_key_values(text)
    topology: dict[str, int] = {}
    for key in (
        "nodes",
        "points",
        "lines",
        "boundaries",
        "centroids",
        "areas",
        "islands",
        "primitives",
        "map3d",
    ):
        if key in values:
            try:
                topology[key] = int(float(values[key]))
            except ValueError:
                topology[key] = 0
    return topology


def classify_geometry(topology: dict[str, int]) -> str:
    """Deterministic geometry classification (contracts/semantic-result.md)."""
    if topology.get("areas", 0) > 0:
        return "area"
    if topology.get("lines", 0) > 0:
        return "line"
    if topology.get("points", 0) > 0:
        return "point"
    if topology.get("boundaries", 0) > 0:
        return "boundary"
    return "empty"


def feature_count(topology: dict[str, int], geometry: str) -> int:
    """Topology-derived count for the declared geometry."""
    key = {
        "area": "areas",
        "line": "lines",
        "point": "points",
        "boundary": "centroids",
    }.get(geometry, "primitives")
    return int(topology.get(key, topology.get("primitives", 0)))


def parse_v_info_columns(text: str) -> list[str]:
    """Each line is `<SQL type>|<column name>`; take the last field."""
    columns: list[str] = []
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        columns.append(line.split("|")[-1])
    return columns


def parse_map_list(text: str) -> list[str]:
    return sorted(line.strip() for line in text.splitlines() if line.strip())


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------


def snapshot_maps(
    runner=None, timeout_s: float = DEFAULT_QUERY_TIMEOUT_S
) -> tuple[dict, str | None]:
    """Snapshot rasters and vectors in the *current* mapset only."""
    run = runner or default_runner
    snapshot: dict[str, list[str]] = {"raster": [], "vector": []}
    for kind in ("raster", "vector"):
        result = run(["g.list", f"type={kind}", "mapset=."], timeout_s)
        if not result.ok:
            return snapshot, ERROR_QUERY_FAILED
        snapshot[kind] = parse_map_list(result.stdout)
    return snapshot, None


def new_maps(before: dict, after: dict) -> dict:
    """Sorted set difference per type; a deleted map never counts."""
    result: dict[str, list[str]] = {}
    for kind in ("raster", "vector"):
        result[kind] = sorted(set(after.get(kind) or []) - set(before.get(kind) or []))
    return result


# --------------------------------------------------------------------------
# Assertion evaluation
# --------------------------------------------------------------------------

_QUERY_BY_TYPE = {
    "raster": "r.univar -g -r map={name}",
    "vector": "v.info -t map={name}",
}


def _assertion_specs(spec: dict, output_name: str) -> list[dict]:
    return [a for a in spec.get("assertions") or [] if a.get("output") == output_name]


def _fail_results(
    spec: dict, output_name: str, detail: str, query: str = ""
) -> list:
    results = []
    for assertion in _assertion_specs(spec, output_name):
        results.append(
            {
                "output": output_name,
                "check": assertion.get("check", ""),
                "expected": _expected_for(assertion),
                "observed": None,
                "tolerance": assertion.get("tolerance"),
                "passed": False,
                "detail": detail,
                "query": query,
            }
        )
    return results


def _expected_for(assertion: dict):
    check = assertion.get("check")
    if check == "value_range":
        return [assertion.get("min_value"), assertion.get("max")]
    if check in ("mean", "geometry_type"):
        return assertion.get("expected")
    if check == "required_columns":
        return list(assertion.get("columns") or [])
    return assertion.get("min")


def _finite(values: list[float]) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _evaluate_assertion(assertion: dict, observed: dict) -> dict:
    check = assertion.get("check")
    passed = False
    detail = ""
    expected = _expected_for(assertion)

    if check == "non_null_count":
        minimum = assertion.get("min", 1)
        actual = observed.get("n", 0)
        passed = actual >= minimum
        detail = f"n={actual} (minimum {minimum})"
        observed_value = actual
    elif check == "value_range":
        lo, hi = assertion.get("min_value"), assertion.get("max")
        actual_min, actual_max = observed.get("min"), observed.get("max")
        passed = (
            lo is not None
            and hi is not None
            and actual_min is not None
            and actual_max is not None
            and actual_min >= lo
            and actual_max <= hi
        )
        detail = f"observed [{actual_min}, {actual_max}], expected [{lo}, {hi}]"
        observed_value = (
            f"{actual_min}–{actual_max}"
            if actual_min is not None and actual_max is not None
            else None
        )
    elif check == "mean":
        expected_mean = assertion.get("expected")
        tolerance = assertion.get("tolerance", 0.01)
        actual_mean = observed.get("mean")
        observed_value = actual_mean
        if expected_mean is None or actual_mean is None:
            passed = False
            detail = "no reference mean or observed mean"
        else:
            delta = abs(actual_mean - expected_mean)
            allowed = abs(tolerance * expected_mean)
            passed = delta <= allowed
            detail = (
                f"observed {actual_mean}, expected {expected_mean}, "
                f"tolerance {tolerance:.2%} (delta {delta:.6g} > {allowed:.6g})"
                if not passed
                else f"within {tolerance:.2%} relative tolerance"
            )
    elif check == "feature_count":
        minimum = assertion.get("min", 1)
        actual = observed.get("feature_count", 0)
        passed = actual >= minimum
        detail = f"feature_count={actual} (minimum {minimum})"
        observed_value = actual
    elif check == "geometry_type":
        expected_geometry = assertion.get("expected")
        actual_geometry = observed.get("geometry")
        passed = expected_geometry is not None and actual_geometry == expected_geometry
        detail = f"geometry={actual_geometry}, expected {expected_geometry}"
        observed_value = actual_geometry
    elif check == "required_columns":
        required = list(assertion.get("columns") or [])
        columns = list(observed.get("columns") or [])
        missing = [column for column in required if column not in columns]
        passed = not missing
        detail = (
            "all required columns present"
            if passed
            else f"missing columns {missing}"
        )
        observed_value = columns
    else:
        detail = f"unknown check {check!r}"
        observed_value = None

    return {
        "output": assertion.get("output", ""),
        "check": check,
        "expected": expected,
        "observed": observed_value,
        "tolerance": assertion.get("tolerance"),
        "passed": bool(passed),
        "detail": detail,
        "query": "",
    }


def evaluate_probe(
    spec: dict,
    maps_after: dict,
    runner=None,
    clock=time.monotonic,
) -> dict:
    """Evaluate every declared output and assertion against one snapshot.

    Every output's existence is resolved exactly once, before any assertion is
    evaluated (I13). One failing output never hides another.
    """
    run = runner or default_runner
    query_timeout = float(spec.get("query_timeout_s", DEFAULT_QUERY_TIMEOUT_S))
    probe_budget = float(spec.get("probe_timeout_s", DEFAULT_PROBE_TIMEOUT_S))
    started = clock()
    error: str | None = None

    outputs_spec = list(spec.get("outputs") or [])
    after = {
        "raster": set(maps_after.get("raster") or []),
        "vector": set(maps_after.get("vector") or []),
    }
    other = {"raster": "vector", "vector": "raster"}

    # --- pass 1: resolve existence exactly once for every declared output
    existence: dict[str, dict] = {}
    for output in outputs_spec:
        name = output.get("name", "")
        kind = output.get("type", "")
        exists = name in after.get(kind, set())
        wrong_type = not exists and name in after.get(other.get(kind, ""), set())
        existence[name] = {"exists": exists, "wrong_type": wrong_type}
        if wrong_type and error is None:
            error = ERROR_WRONG_TYPE
        elif not exists and not wrong_type and error is None:
            error = ERROR_MISSING_OUTPUT

    results: list[dict] = []
    for output in outputs_spec:
        name = output.get("name", "")
        kind = output.get("type", "")
        state = existence.get(name, {})
        observed: dict = {}

        if not state.get("exists"):
            detail = (
                f"output {name!r} exists as the wrong type"
                if state.get("wrong_type")
                else f"output {name!r} is missing from the scratch mapset"
            )
            assertions = _fail_results(
                spec, name, detail, _QUERY_BY_TYPE.get(kind, "").format(name=name)
            )
            results.append(
                {
                    "name": name,
                    "type": kind,
                    "exists": False,
                    "observed": {},
                    "assertions": assertions,
                }
            )
            continue

        if clock() - started > probe_budget:
            if error is None:
                error = ERROR_PROBE_TIMEOUT
            assertions = _fail_results(spec, name, "probe timeout", "")
            results.append(
                {
                    "name": name,
                    "type": kind,
                    "exists": True,
                    "observed": {},
                    "assertions": assertions,
                }
            )
            continue

        if kind == "raster":
            query = ["r.univar", "-g", "-r", f"map={name}"]
            query_text = "r.univar -g -r map={name}".format(name=name)
            query_result = run(query, query_timeout)
            if query_result.timed_out:
                error = error or ERROR_QUERY_TIMEOUT
                assertions = _fail_results(
                    spec, name, "r.univar timed out", query_text
                )
            elif not query_result.ok:
                error = error or ERROR_QUERY_FAILED
                assertions = _fail_results(
                    spec, name, f"r.univar failed ({query_result.returncode})", query_text
                )
            else:
                try:
                    observed = parse_univar(query_result.stdout)
                except (ValueError, TypeError):
                    error = error or ERROR_PARSE_ERROR
                    assertions = _fail_results(
                        spec, name, "r.univar output did not parse", query_text
                    )
                else:
                    values = [observed["min"], observed["max"], observed["mean"]]
                    if observed.get("n", 0) <= 0:
                        error = error or ERROR_NO_VALUES
                        assertions = _fail_results(
                            spec, name, "r.univar returned n=0", query_text
                        )
                    elif not _finite(values):
                        error = error or ERROR_NON_FINITE
                        assertions = _fail_results(
                            spec, name, "r.univar returned a non-finite value", query_text
                        )
                    else:
                        assertions = [
                            _evaluate_assertion(a, observed)
                            for a in _assertion_specs(spec, name)
                        ]
                        for assertion in assertions:
                            assertion["query"] = query_text
        else:
            topology_query = ["v.info", "-t", f"map={name}"]
            topology_text = "v.info -t map={name}".format(name=name)
            topology_result = run(topology_query, query_timeout)
            if topology_result.timed_out:
                error = error or ERROR_QUERY_TIMEOUT
                assertions = _fail_results(
                    spec, name, "v.info -t timed out", topology_text
                )
            elif not topology_result.ok:
                error = error or ERROR_QUERY_FAILED
                assertions = _fail_results(
                    spec, name, "v.info -t failed", topology_text
                )
            else:
                topology = parse_v_info_topology(topology_result.stdout)
                geometry = classify_geometry(topology)
                observed = {
                    "feature_count": feature_count(topology, geometry),
                    "geometry": geometry,
                    "topology": topology,
                    "columns": [],
                }
                columns_result = run(
                    ["v.info", "-c", f"map={name}"], query_timeout
                )
                if columns_result.timed_out:
                    error = error or ERROR_QUERY_TIMEOUT
                elif columns_result.ok:
                    observed["columns"] = parse_v_info_columns(columns_result.stdout)
                # A vector with no attribute table exits non-zero; that is only
                # a failure when the case declared required columns.

                assertions = [
                    _evaluate_assertion(a, observed)
                    for a in _assertion_specs(spec, name)
                ]
                for assertion in assertions:
                    assertion["query"] = (
                        "v.info -c map={name}".format(name=name)
                        if "columns" in assertion["detail"]
                        or assertion["check"] == "required_columns"
                        else topology_text
                    )

        results.append(
            {
                "name": name,
                "type": kind,
                "exists": True,
                "observed": observed,
                "assertions": assertions,
            }
        )

    passed = error is None and all(
        assertion.get("passed", False)
        for output in results
        for assertion in output.get("assertions") or []
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": spec.get("case_id", ""),
        "evaluated": True,
        "passed": bool(passed),
        "new_maps": maps_after,
        "outputs": results,
        "error": error,
        "elapsed_s": max(0.0, clock() - started),
    }


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def _write_atomic(path: Path | str, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return path


def write_maps(maps_out: Path | str | None, payload: dict) -> None:
    if maps_out:
        _write_atomic(maps_out, payload)


def write_semantic(semantic_out: Path | str | None, payload: dict) -> None:
    if semantic_out:
        _write_atomic(semantic_out, payload)


def run_probe(
    spec: dict,
    maps_before: dict,
    maps_after: dict,
    runner=None,
    maps_out: Path | str | None = None,
    semantic_out: Path | str | None = None,
    clock=time.monotonic,
) -> dict:
    """Evaluate the spec and atomically persist maps.json / semantic.json."""
    discovered = new_maps(maps_before, maps_after)
    if maps_out:
        write_maps(
            maps_out,
            {
                "schema_version": SCHEMA_VERSION,
                "case_id": spec.get("case_id", ""),
                "before": {
                    "raster": sorted(maps_before.get("raster") or []),
                    "vector": sorted(maps_before.get("vector") or []),
                },
                "after": {
                    "raster": sorted(maps_after.get("raster") or []),
                    "vector": sorted(maps_after.get("vector") or []),
                },
                "new_maps": discovered,
                "error": None,
            },
        )
    semantic = evaluate_probe(spec, maps_after, runner=runner, clock=clock)
    semantic["new_maps"] = discovered
    write_semantic(semantic_out, semantic)
    return semantic


if __name__ == "__main__":  # pragma: no cover - run only inside a session
    spec_path = os.environ.get("GRASS_AGENT_SEMANTIC_SPEC")
    if not spec_path:
        raise SystemExit("GRASS_AGENT_SEMANTIC_SPEC is not set")
    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    before, _ = snapshot_maps()
    after, _ = snapshot_maps()
    run_probe(
        spec,
        before,
        after,
        maps_out=os.environ.get("GRASS_AGENT_MAPS_OUT"),
        semantic_out=os.environ.get("GRASS_AGENT_SEMANTIC_OUT"),
    )
