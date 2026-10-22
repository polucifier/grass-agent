"""Auxiliary input resolution and staging (FR-001b).

Benchmark cases may reference files that live neither in the target dataset nor
in the knowledge base. Each such file must be *declared* on the case and staged
into the attempt's scratch directory.

The harness never synthesises an undeclared file (clarification Q2). Doing so
would mask a genuine agent error: the script references a name that does not
exist, and that is precisely what `missing_input` is supposed to measure. A
missing-input failure must therefore always mean the model got the name wrong,
never that the harness forgot to prepare something.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

# Shapefile components that share a stem and must travel together.
SHAPEFILE_SUFFIXES = (".shp", ".shx", ".dbf", ".prj")


class FixtureError(Exception):
    """A declared auxiliary input is unusable.

    This is a harness configuration error, not a benchmark failure: the case
    declared something the operator never provisioned.
    """


@dataclass
class StagedFixture:
    """One declared auxiliary input, after resolution."""

    name: str
    sources: list[Path]
    target: Path | None = None


def resolve_fixture(fixtures_dir: Path, name: str) -> list[Path]:
    """Resolve a declared fixture name to concrete files.

    Resolution rules:
      - a bare filename or relative path resolves under `fixtures_dir`
      - a shapefile stem expands to every sibling sharing it
      - an absolute path, or one escaping `fixtures_dir` after normalisation,
        is rejected as a harness configuration error

    Returns an empty list when nothing matches, letting the caller decide
    whether that is fatal (pre-flight) or a benchmark outcome.
    """
    if not name or not name.strip():
        raise FixtureError("empty fixture name")

    base = Path(fixtures_dir).resolve()
    candidate = Path(name)
    if candidate.is_absolute():
        raise FixtureError(f"{name}: absolute paths are not allowed")

    target = (base / candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise FixtureError(f"{name}: escapes the fixtures directory") from None

    if target.is_dir():
        return sorted(p for p in target.iterdir() if p.is_file())

    if target.suffix.lower() in SHAPEFILE_SUFFIXES:
        stem = target.with_suffix("")
        siblings = [
            Path(str(stem) + suffix)
            for suffix in SHAPEFILE_SUFFIXES
            if Path(str(stem) + suffix).is_file()
        ]
        if siblings:
            return sorted(siblings)

    if target.is_file():
        return [target]
    return []


def stage_fixtures(fixtures_dir: Path, scratch_dir: Path, names: list[str]) -> list[StagedFixture]:
    """Copy declared fixtures into `scratch_dir`.

    Copies rather than moves: the originals under `benchmarks/fixtures/` are the
    operator's provisioning, and a later attempt on the same case needs them
    again.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    staged: list[StagedFixture] = []
    for name in names:
        sources = resolve_fixture(fixtures_dir, name)
        if not sources:
            raise FixtureError(f"{name}: not found under {fixtures_dir}")
        entry = StagedFixture(name=name, sources=sources)
        for source in sources:
            destination = scratch_dir / source.name
            shutil.copy2(source, destination)
            if entry.target is None:
                entry.target = destination
            else:
                entry.target = destination
        staged.append(entry)
    return staged


def required_fixtures(test_cases: list[dict]) -> list[tuple[str, str]]:
    """Flatten (case_id, fixture) pairs across a suite, for pre-flight."""
    pairs: list[tuple[str, str]] = []
    for case in test_cases:
        for name in case.get("auxiliary_inputs", []) or []:
            pairs.append((case["id"], name))
    return pairs


def load_suite(path: Path) -> list[dict]:
    """Read a benchmark suite, tolerating a missing `auxiliary_inputs` key.

    `tier` lives at file level in tier2 but not tier1, so it is propagated onto
    every case -- otherwise the report's Tier column reads "-" for all of tier 1
    and mislabels half the suite.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("test_cases", [])
    # tier2 declares `tier` at file level; tier1 omits it entirely. Infer tier 1
    # from the absence so the report never labels half the suite as unknown.
    tier = data.get("tier", 1)
    for case in cases:
        case.setdefault("tier", tier)
    return cases


def filter_cases(test_cases: list[dict], case_ids: tuple[str, ...]) -> list[dict]:
    """Apply a `-k/--case` filter, preserving suite order."""
    if not case_ids:
        return test_cases
    wanted = set(case_ids)
    return [case for case in test_cases if case["id"] in wanted]


def unmatched_ids(test_cases: list[dict], case_ids: tuple[str, ...]) -> list[str]:
    """Case ids from the filter that matched nothing (an argument error)."""
    if not case_ids:
        return []
    present = {case["id"] for case in test_cases}
    return sorted(set(case_ids) - present)