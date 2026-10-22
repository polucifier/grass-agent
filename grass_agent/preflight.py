"""Pre-flight dependency checks (FR-023).

Every dependency is checked once per run, before any case executes, so a
missing dependency costs one clear exit rather than 40 identical per-case
failures.

Exit codes follow contracts/cli.md:

    2  argument error
    3  missing runtime dependency (message names which one)
    1  harness fault
"""

from __future__ import annotations

import sqlite3
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import DatasetNotFound, ExecutionConfig, GrassUnavailable, grass_config

EXIT_OK = 0
EXIT_FAULT = 1
EXIT_ARG = 2
EXIT_MISSING_DEPENDENCY = 3

# Files a GRASS PERMANENT mapset must contain for the project to be usable.
_REQUIRED_PERMANENT_FILES = ("DEFAULT_WIND", "PROJ_INFO")


class MissingDependency(Exception):
    """A required runtime dependency is absent.

    FR-023 requires the process to exit non-zero *and* name the dependency.
    """

    def __init__(self, name: str, detail: str, hint: str = ""):
        self.name = name
        self.detail = detail
        self.hint = hint
        message = f"missing dependency [{name}]: {detail}"
        if hint:
            message += f"\n  hint: {hint}"
        super().__init__(message)


@dataclass
class PreflightReport:
    """Outcome of a pre-flight pass."""

    ok: bool
    checked: list[str]
    failures: list[MissingDependency]
    dataset_project: Path | None = None
    tmp_mapset_supported: bool = True

    @property
    def first_failure(self) -> MissingDependency | None:
        return self.failures[0] if self.failures else None


def check_grass_installed(config: ExecutionConfig) -> str:
    """Confirm the GRASS launcher works and return its configured path."""
    try:
        return grass_config("path", config.grass_bin)
    except GrassUnavailable as exc:
        raise MissingDependency(
            "GRASS installation",
            str(exc),
            "install GRASS GIS and ensure 'grass' is on PATH",
        ) from exc


def check_tmp_mapset_supported(config: ExecutionConfig) -> bool:
    """True when the GRASS CLI exposes `--tmp-mapset`.

    When unsupported, the caller falls back to the grass.script.setup.init()
    worker (see fallback_worker.py). A GRASS that lacks --tmp-mapset is not a
    missing dependency -- it selects the execution strategy.
    """
    try:
        result = subprocess.run(
            [config.grass_bin, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    combined = (result.stdout or "") + (result.stderr or "")
    return "--tmp-mapset" in combined


def check_dataset(config: ExecutionConfig) -> Path:
    """Resolve and validate the dataset project (FR-023)."""
    try:
        if config.dataset_project is None:
            resolved = ExecutionConfig.detect_dataset(config.grass_bin)
            return Path(resolved.dataset_project)
    except DatasetNotFound as exc:
        raise MissingDependency(
            "GRASS sample dataset",
            str(exc),
            "provision the North Carolina dataset manually -- "
            "see benchmarks/fixtures/README.md (the harness never downloads it)",
        ) from exc

    project = Path(config.dataset_project)
    if not ExecutionConfig.is_valid_project(project):
        permanent = project / "PERMANENT"
        missing = [
            f
            for f in _REQUIRED_PERMANENT_FILES
            if not (permanent / f).is_file()
        ]
        detail = (
            f"{project} is not a usable GRASS project"
            + (f"; missing {', '.join(missing)}" if missing else "")
        )
        raise MissingDependency(
            "GRASS sample dataset",
            detail,
            "point --dataset at a GRASS project directory containing a valid PERMANENT",
        )
    return project


def check_model_service(config: ExecutionConfig) -> None:
    """Confirm the local Ollama service is reachable (FR-016, FR-023)."""
    url = config.ollama_base_url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise MissingDependency(
            "local model service",
            f"cannot reach Ollama at {config.ollama_base_url}: {exc}",
            "start it with 'ollama serve'",
        ) from exc


def check_knowledge_db(config: ExecutionConfig) -> Path:
    """Confirm the tool knowledge base is readable and non-empty (FR-001)."""
    db_path = Path(config.knowledge_db)
    if not db_path.is_file():
        raise MissingDependency(
            "knowledge base",
            f"{db_path} does not exist",
            "build data/grass_knowledge.db before running the harness",
        )
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            count = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
    except sqlite3.Error as exc:
        raise MissingDependency(
            "knowledge base", f"{db_path} is not readable as sqlite: {exc}"
        ) from exc
    if count == 0:
        raise MissingDependency("knowledge base", f"{db_path} contains no tools")
    return db_path


def check_fixtures(config: ExecutionConfig, required: list[tuple[str, str]]) -> list[Path]:
    """Resolve every fixture a selected case declares (FR-001b).

    `required` is a list of (case_id, fixture_name) pairs. Imports the
    resolver lazily so this module stays importable without fixtures present.
    """
    from .fixtures import FixtureError, resolve_fixture

    resolved: list[Path] = []
    missing: list[str] = []
    for case_id, name in required:
        try:
            matches = resolve_fixture(Path(config.fixtures_dir), name)
        except FixtureError as exc:
            missing.append(f"{case_id}: {exc}")
            continue
        if matches:
            resolved.extend(matches)
    if missing:
        raise MissingDependency(
            "benchmark fixtures",
            "unresolvable auxiliary_inputs -- " + "; ".join(missing),
            f"add the file(s) under {config.fixtures_dir}/ or remove the declaration",
        )
    return resolved


def check_reuse_artifacts(config: ExecutionConfig) -> Path:
    """Confirm persisted Gate 1 scripts exist for --reuse-artifacts."""
    artifacts = Path(config.reuse_artifacts_dir)
    if not artifacts.is_dir():
        raise MissingDependency(
            "Gate 1 artifacts",
            f"{artifacts} does not exist",
            "run benchmarks/run_gate1.py first, or omit --reuse-artifacts",
        )
    return artifacts


def run_preflight(
    config: ExecutionConfig,
    required_fixtures: list[tuple[str, str]] | None = None,
    need_reuse_artifacts: bool = False,
) -> PreflightReport:
    """Run every check, collecting all failures rather than stopping at the first.

    Reporting them together saves a user several edit-and-rerun cycles.
    """
    checked: list[str] = []
    failures: list[MissingDependency] = []
    project: Path | None = None
    tmp_mapset = True

    checks = [
        ("GRASS installation", lambda: check_grass_installed(config)),
        ("dataset", lambda: check_dataset(config)),
        ("local model service", lambda: check_model_service(config)),
        ("knowledge base", lambda: check_knowledge_db(config)),
    ]
    if required_fixtures:
        checks.append(("benchmark fixtures", lambda: check_fixtures(config, required_fixtures)))
    if need_reuse_artifacts:
        checks.append(("Gate 1 artifacts", lambda: check_reuse_artifacts(config)))

    for name, check in checks:
        checked.append(name)
        try:
            result = check()
        except MissingDependency as exc:
            failures.append(exc)
            continue
        if name == "dataset" and isinstance(result, Path):
            project = result

    # --tmp-mapset support selects the execution strategy rather than being a
    # hard dependency, so it is probed separately and never a failure.
    checked.append("CLI sandbox support")
    if not any(f.name == "GRASS installation" for f in failures):
        tmp_mapset = check_tmp_mapset_supported(config)

    return PreflightReport(
        ok=not failures,
        checked=checked,
        failures=failures,
        dataset_project=project,
        tmp_mapset_supported=tmp_mapset,
    )