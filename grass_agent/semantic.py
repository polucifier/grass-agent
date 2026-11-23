"""Pilot suite, assertion models, and probe-result normalization (FR-007..FR-009).

The semantic oracle is deliberately split in two:

* this module owns the *declared* shape — the pilot cases, their outputs, their
  assertions, and the frozen reference expectations; and
* `semantic_probe.py` owns the *measurement* — read-only queries executed inside
  the candidate's own scratch GRASS session.

Nothing here derives an expected value from candidate output. Expected values
come only from `benchmarks/pilot_expectations.json`, which
`benchmarks/derive_pilot_expectations.py` produces from human-reviewed reference
scripts (FR-007d).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHECKS = (
    "non_null_count",
    "value_range",
    "mean",
    "feature_count",
    "geometry_type",
    "required_columns",
)
OUTPUT_TYPES = ("raster", "vector")
GEOMETRIES = ("point", "line", "area", "boundary")

# A reference value is the only admissible authority. Anything else would let a
# candidate grade its own homework.
EXPECTED_SOURCES = ("reference",)

DEFAULT_MEAN_TOLERANCE = 0.01
DEFAULT_COUNT_MIN = 1
PILOT_PREFIX = "pilot_"
PILOT_CASE_COUNT = 10
MIN_CASES_PER_BENCHMARK_TIER = 4
MIN_MULTI_STEP_CASES = 2
REGION_SENTENCE = "Do not change the computational region."

# Tools that create no persistent map. A pilot case whose only tools are here is
# display-only or statistics-only and is excluded by FR-007a.
DISPLAY_ONLY_TOOLS = frozenset(
    {
        "d.rast",
        "d.vect",
        "d.legend",
        "d.barscale",
        "d.grid",
        "d.erase",
        "d.redraw",
        "r.univar",
        "r.stats",
        "v.info",
        "r.info",
        "g.region",
        "g.list",
        "g.gisenv",
        "r.report",
        "v.report",
        "r.what",
        "v.what",
    }
)


# --------------------------------------------------------------------------
# Entities (data-model sections 2, 3, 4, 6, 7)
# --------------------------------------------------------------------------


@dataclass
class OutputSpec:
    """One declared output map."""

    name: str
    type: str
    geometry: str | None = None


@dataclass
class AssertionSpec:
    """One declared check. The spec carries the check; expectations carry values."""

    output: str
    check: str
    min: float | None = None
    max: float | None = None
    min_value: float | None = None
    expected: str | float | None = None
    columns: list[str] = field(default_factory=list)
    tolerance: float | None = None
    expected_source: str = "reference"


@dataclass
class CaseSemantics:
    """The semantic declaration for one pilot case."""

    case_id: str
    outputs: list[OutputSpec] = field(default_factory=list)
    assertions: list[AssertionSpec] = field(default_factory=list)

    def output(self, name: str) -> OutputSpec | None:
        for spec in self.outputs:
            if spec.name == name:
                return spec
        return None


@dataclass
class PilotExpectations:
    """Frozen reference values, one file for the suite."""

    version: str = ""
    generated_at: str = ""
    generator: str = ""
    grass_version: str = ""
    dataset: dict = field(default_factory=dict)
    cases: dict = field(default_factory=dict)

    def case(self, case_id: str) -> dict | None:
        return self.cases.get(case_id)

    def output(self, case_id: str, output_name: str) -> dict | None:
        case = self.case(case_id)
        if not case:
            return None
        return (case.get("outputs") or {}).get(output_name)


@dataclass
class AssertionResult:
    """One evaluated check, persisted as evidence (data-model section 6)."""

    output: str
    check: str
    expected: object = None
    observed: object = None
    tolerance: float | None = None
    passed: bool = False
    detail: str = ""
    query: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "AssertionResult":
        return cls(
            output=payload.get("output", ""),
            check=payload.get("check", ""),
            expected=payload.get("expected"),
            observed=payload.get("observed"),
            tolerance=payload.get("tolerance"),
            passed=bool(payload.get("passed", False)),
            detail=payload.get("detail", ""),
            query=payload.get("query", ""),
        )


@dataclass
class OutputResult:
    """Per-output probe evidence. Not one of the six core dataclasses, but the
    persisted `semantic.json` needs a typed representation."""

    name: str
    type: str
    exists: bool = False
    observed: dict = field(default_factory=dict)
    assertions: list[AssertionResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "exists": self.exists,
            "observed": dict(self.observed),
            "assertions": [a.to_dict() for a in self.assertions],
        }


@dataclass
class SemanticResult:
    """The normalized outcome of the in-session probe (data-model section 7)."""

    evaluated: bool = False
    passed: bool = False
    case_id: str = ""
    new_maps: dict = field(default_factory=lambda: {"raster": [], "vector": []})
    outputs: list[OutputResult] = field(default_factory=list)
    error: str | None = None
    elapsed_s: float = 0.0

    @property
    def assertion_results(self) -> list[dict]:
        results: list[dict] = []
        for output in self.outputs:
            for assertion in output.assertions:
                results.append(assertion.to_dict())
        return results

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "case_id": self.case_id,
            "evaluated": self.evaluated,
            "passed": self.passed,
            "new_maps": {
                "raster": sorted(self.new_maps.get("raster") or []),
                "vector": sorted(self.new_maps.get("vector") or []),
            },
            "outputs": [o.to_dict() for o in self.outputs],
            "error": self.error,
            "elapsed_s": self.elapsed_s,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SemanticResult":
        outputs = []
        for entry in payload.get("outputs") or []:
            outputs.append(
                OutputResult(
                    name=entry.get("name", ""),
                    type=entry.get("type", ""),
                    exists=bool(entry.get("exists", False)),
                    observed=dict(entry.get("observed") or {}),
                    assertions=[
                        AssertionResult.from_dict(a)
                        for a in entry.get("assertions") or []
                    ],
                )
            )
        new_maps = payload.get("new_maps") or {}
        return cls(
            evaluated=bool(payload.get("evaluated", False)),
            passed=bool(payload.get("passed", False)),
            case_id=payload.get("case_id", ""),
            new_maps={
                "raster": sorted(new_maps.get("raster") or []),
                "vector": sorted(new_maps.get("vector") or []),
            },
            outputs=outputs,
            error=payload.get("error"),
            elapsed_s=float(payload.get("elapsed_s") or 0.0),
        )


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def case_semantics(case: dict) -> CaseSemantics:
    """Build the semantic declaration from a raw pilot case dict."""
    outputs = [
        OutputSpec(
            name=output["name"],
            type=output.get("type", ""),
            geometry=output.get("geometry"),
        )
        for output in case.get("outputs") or []
    ]
    assertions = [
        AssertionSpec(
            output=assertion.get("output", ""),
            check=assertion.get("check", ""),
            min=assertion.get("min"),
            max=assertion.get("max"),
            min_value=assertion.get("min_value"),
            expected=assertion.get("expected"),
            columns=list(assertion.get("columns") or []),
            tolerance=assertion.get("tolerance"),
            expected_source=assertion.get("expected_source", "reference"),
        )
        for assertion in case.get("assertions") or []
    ]
    return CaseSemantics(case_id=case.get("id", ""), outputs=outputs, assertions=assertions)


def load_pilot_suite(path: Path | str) -> dict:
    """Read the pilot suite JSON."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_expectations(path: Path | str) -> PilotExpectations:
    """Read and type the frozen expectations file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return PilotExpectations(
        version=payload.get("version", ""),
        generated_at=payload.get("generated_at", ""),
        generator=payload.get("generator", ""),
        grass_version=payload.get("grass_version", ""),
        dataset=dict(payload.get("dataset") or {}),
        cases=dict(payload.get("cases") or {}),
    )


def pilot_cases(suite: dict) -> list[dict]:
    return list(suite.get("test_cases") or [])


# --------------------------------------------------------------------------
# Validation (FR-007a, contracts/pilot-suite.md "Validation")
# --------------------------------------------------------------------------


def validate_pilot_suite(
    suite: dict,
    expectations: PilotExpectations | None = None,
    reference_dir: Path | str | None = None,
    current_grass_version: str | None = None,
    current_dataset: dict | None = None,
) -> list[str]:
    """Return every named violation; an empty list means the pilot is valid.

    Composition, naming, and assertion validity are always checked. Reference
    hashes and environment identity are checked when the corresponding inputs
    are supplied (that is what `--validate-pilot` does).
    """
    violations: list[str] = []
    cases = pilot_cases(suite)

    # --- composition
    if len(cases) != PILOT_CASE_COUNT:
        violations.append(
            f"composition: expected exactly {PILOT_CASE_COUNT} cases, found {len(cases)}"
        )

    tier1 = sum(1 for c in cases if _benchmark_tier(c) == 1)
    tier2 = sum(1 for c in cases if _benchmark_tier(c) == 2)
    if tier1 < MIN_CASES_PER_BENCHMARK_TIER:
        violations.append(
            f"composition: Tier 1 has {tier1} cases, need at least "
            f"{MIN_CASES_PER_BENCHMARK_TIER}"
        )
    if tier2 < MIN_CASES_PER_BENCHMARK_TIER:
        violations.append(
            f"composition: Tier 2 has {tier2} cases, need at least "
            f"{MIN_CASES_PER_BENCHMARK_TIER}"
        )

    multi_step = sum(1 for c in cases if _is_multi_step_or_mixed(c))
    if multi_step < MIN_MULTI_STEP_CASES:
        violations.append(
            f"composition: {multi_step} multi-step/mixed cases, need at least "
            f"{MIN_MULTI_STEP_CASES}"
        )

    has_raster = any(
        o.get("type") == "raster" for c in cases for o in c.get("outputs") or []
    )
    has_vector = any(
        o.get("type") == "vector" for c in cases for o in c.get("outputs") or []
    )
    if cases and not (has_raster and has_vector):
        violations.append(
            "composition: the pilot must declare at least one raster and one "
            "vector output"
        )

    # --- per-case shape
    for case in cases:
        case_id = case.get("id", "<missing id>")
        outputs = case.get("outputs") or []
        assertions = case.get("assertions") or []

        if not outputs:
            violations.append(
                f"{case_id}: composition violation: no persistent output "
                f"(display-only or statistics-only case, FR-007a)"
            )
        if not assertions:
            violations.append(f"{case_id}: no assertions declared")

        if _is_display_only(case):
            violations.append(
                f"{case_id}: composition violation: display-only/statistics-only "
                f"task produces no persistent map (FR-007a)"
            )

        names = [o.get("name", "") for o in outputs]
        if len(set(names)) != len(names):
            violations.append(f"{case_id}: duplicate output names {names}")

        declared = set(names)
        prompt = case.get("prompt", "")
        for output in outputs:
            name = output.get("name", "")
            if not name.startswith(PILOT_PREFIX):
                violations.append(
                    f"{case_id}: output {name!r} does not start with {PILOT_PREFIX!r}"
                )
            if name and name not in prompt:
                violations.append(
                    f"{case_id}: output {name!r} does not appear verbatim in the prompt"
                )
            if output.get("type") not in OUTPUT_TYPES:
                violations.append(
                    f"{case_id}: output {name!r} has invalid type "
                    f"{output.get('type')!r}"
                )

        for assertion in assertions:
            output_name = assertion.get("output")
            check = assertion.get("check")
            if output_name not in declared:
                violations.append(
                    f"{case_id}: assertion references undeclared output "
                    f"{output_name!r}"
                )
            if check not in CHECKS:
                violations.append(
                    f"{case_id}: assertion on {output_name!r} has unknown check "
                    f"{check!r}"
                )
                continue
            source = assertion.get("expected_source", "reference")
            if source not in EXPECTED_SOURCES:
                violations.append(
                    f"{case_id}: assertion on {output_name!r} declares "
                    f"expected_source {source!r}; only 'reference' is admissible"
                )
            violations.extend(_assertion_value_violations(case_id, assertion))

    if expectations is not None:
        violations.extend(_expectation_violations(cases, expectations))

    if reference_dir is not None and expectations is not None:
        violations.extend(_reference_hash_violations(expectations, Path(reference_dir)))

    if current_grass_version and expectations is not None:
        if expectations.grass_version and current_grass_version != expectations.grass_version:
            violations.append(
                f"environment: GRASS version is {current_grass_version}, reference "
                f"expectations record {expectations.grass_version}"
            )

    if current_dataset and expectations is not None:
        expected_project = (expectations.dataset or {}).get("project")
        current_project = (current_dataset or {}).get("project")
        if expected_project and current_project and Path(expected_project) != Path(current_project):
            violations.append(
                f"environment: dataset is {current_project}, reference "
                f"expectations record {expected_project}"
            )
        expected_hash = (expectations.dataset or {}).get("permanent_hash")
        current_hash = (current_dataset or {}).get("permanent_hash")
        if expected_hash and current_hash and expected_hash != current_hash:
            violations.append(
                "environment: PERMANENT hash differs from the reference "
                "expectations"
            )

    return violations


def _benchmark_tier(case: dict) -> int | None:
    tier = case.get("tier")
    if tier is not None:
        return int(tier)
    suite = case.get("source_suite")
    if suite == "tier1":
        return 1
    if suite == "tier2":
        return 2
    return None


def _is_multi_step_or_mixed(case: dict) -> bool:
    if case.get("category") == "multi_step":
        return True
    types = {o.get("type") for o in case.get("outputs") or []}
    return "raster" in types and "vector" in types


def _is_display_only(case: dict) -> bool:
    tools = [t for t in case.get("expected_tools") or [] if t]
    if not tools:
        return False
    return all(t in DISPLAY_ONLY_TOOLS or t.startswith("d.") for t in tools)


def _assertion_value_violations(case_id: str, assertion: dict) -> list[str]:
    check = assertion.get("check")
    output = assertion.get("output")
    problems: list[str] = []
    if check == "value_range":
        if assertion.get("min_value") is None and assertion.get("max") is None:
            # Bounds may come from the reference expectations instead.
            pass
        else:
            lo = assertion.get("min_value")
            hi = assertion.get("max")
            if lo is not None and hi is not None and float(lo) > float(hi):
                problems.append(
                    f"{case_id}: value_range on {output!r} has min_value {lo} > max {hi}"
                )
    elif check == "mean":
        tolerance = assertion.get("tolerance")
        if tolerance is not None and float(tolerance) < 0:
            problems.append(
                f"{case_id}: mean on {output!r} has negative tolerance {tolerance}"
            )
    elif check == "geometry_type":
        expected = assertion.get("expected")
        if expected is not None and expected not in GEOMETRIES:
            problems.append(
                f"{case_id}: geometry_type on {output!r} declares invalid "
                f"geometry {expected!r}"
            )
    elif check == "required_columns":
        if not assertion.get("columns"):
            problems.append(
                f"{case_id}: required_columns on {output!r} declares no columns"
            )
    elif check in ("non_null_count", "feature_count"):
        minimum = assertion.get("min")
        if minimum is not None and float(minimum) < 0:
            problems.append(
                f"{case_id}: {check} on {output!r} has negative minimum {minimum}"
            )
    return problems


def _expectation_violations(
    cases: list[dict], expectations: PilotExpectations
) -> list[str]:
    problems: list[str] = []
    for case in cases:
        case_id = case.get("id", "")
        if expectations.case(case_id) is None:
            problems.append(f"{case_id}: missing from the expectations file")
            continue
        for output in case.get("outputs") or []:
            name = output.get("name", "")
            if expectations.output(case_id, name) is None:
                problems.append(
                    f"{case_id}: expectations missing output {name!r}"
                )
    return problems


def _reference_hash_violations(
    expectations: PilotExpectations, reference_dir: Path
) -> list[str]:
    problems: list[str] = []
    for case_id, entry in sorted(expectations.cases.items()):
        recorded = entry.get("reference_script_sha256")
        script = entry.get("reference_script")
        if not recorded:
            continue
        if script:
            path = Path(script)
            if not path.is_absolute():
                path = reference_dir.parent.parent / path
        else:
            path = reference_dir / f"{case_id}.py"
        if not path.is_file():
            # Accept a reference dir passed directly.
            alternative = reference_dir / path.name
            path = alternative if alternative.is_file() else path
        if not path.is_file():
            problems.append(
                f"{case_id}: reference script {path} is missing"
            )
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != recorded:
            problems.append(
                f"{case_id}: reference script hash drifted "
                f"({path.name}: {digest[:12]} != {recorded[:12]})"
            )
    return problems


# --------------------------------------------------------------------------
# Assertion resolution
# --------------------------------------------------------------------------


def resolve_assertions(
    semantics: CaseSemantics, expectations_case: dict | None
) -> list[dict]:
    """Merge suite checks/tolerances with frozen reference values.

    Refuses any `expected_source` other than `"reference"`: a candidate-derived
    expectation would make the oracle measure itself.
    """
    resolved: list[dict] = []
    for spec in semantics.assertions:
        if spec.expected_source not in EXPECTED_SOURCES:
            raise ValueError(
                f"assertion on {spec.output!r} declares expected_source "
                f"{spec.expected_source!r}; only 'reference' is admissible"
            )
        reference = None
        if expectations_case:
            reference = (expectations_case.get("outputs") or {}).get(spec.output)

        entry = {
            "output": spec.output,
            "check": spec.check,
        }
        if spec.check == "non_null_count":
            entry["min"] = spec.min if spec.min is not None else DEFAULT_COUNT_MIN
        elif spec.check == "value_range":
            min_value = spec.min_value
            max_value = spec.max
            if min_value is None and reference is not None:
                min_value = reference.get("min")
            if max_value is None and reference is not None:
                max_value = reference.get("max")
            entry["min_value"] = min_value
            entry["max"] = max_value
        elif spec.check == "mean":
            if reference is None or reference.get("mean") is None:
                raise ValueError(
                    f"mean assertion on {spec.output!r} has no reference mean"
                )
            entry["expected"] = reference.get("mean")
            entry["tolerance"] = (
                spec.tolerance if spec.tolerance is not None else DEFAULT_MEAN_TOLERANCE
            )
        elif spec.check == "feature_count":
            entry["min"] = spec.min if spec.min is not None else DEFAULT_COUNT_MIN
        elif spec.check == "geometry_type":
            expected = spec.expected
            if expected is None and reference is not None:
                expected = reference.get("geometry")
            if expected is None:
                raise ValueError(
                    f"geometry_type assertion on {spec.output!r} has no expected "
                    f"geometry"
                )
            entry["expected"] = expected
        elif spec.check == "required_columns":
            entry["columns"] = list(spec.columns)
        else:
            raise ValueError(f"unknown assertion check {spec.check!r}")
        resolved.append(entry)
    return resolved


def build_semantic_spec(
    case: dict,
    expectations: PilotExpectations | None,
    *,
    query_timeout_s: int = 30,
    probe_timeout_s: int = 60,
) -> dict:
    """Build the `semantic_spec.json` payload handed to the in-session probe."""
    semantics = case_semantics(case)
    expectations_case = expectations.case(case["id"]) if expectations else None
    return {
        "schema_version": 1,
        "case_id": case["id"],
        "query_timeout_s": query_timeout_s,
        "probe_timeout_s": probe_timeout_s,
        "outputs": [asdict(o) for o in semantics.outputs],
        "assertions": resolve_assertions(semantics, expectations_case),
    }


def normalize_probe_result(payload: dict, case_id: str | None = None) -> SemanticResult:
    """Convert raw `semantic.json` into harness entities."""
    result = SemanticResult.from_dict(payload)
    if case_id and not result.case_id:
        result.case_id = case_id
    return result
