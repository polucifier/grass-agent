"""Test fixtures shared across the Gate 2 suite.

Every integration test in this project talks to a real GRASS session. The
fixtures here make the environmental preconditions explicit and skippable so a
unit test never fails merely because the host lacks a provisioned dataset.

See tasks T002a and T004.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _grass_available() -> bool:
    """True when `grass --version` succeeds on PATH."""
    if shutil.which("grass") is None:
        return False
    try:
        return subprocess.run(
            ["grass", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def grass_available() -> bool:
    return _grass_available()


@pytest.fixture(scope="session")
def dataset_project(grass_available: bool) -> Path | None:
    """Resolve the North Carolina project, or skip.

    Detection order matches contracts/cli.md and ExecutionConfig.detect_dataset:
    $GISDBASE, $GRASSDATA, ~/grassdata, ./grassdata.
    """
    if not grass_available:
        pytest.skip("GRASS is not available on this host")

    from grass_agent.config import ExecutionConfig, DatasetNotFound

    override = os.environ.get("GRASS_DATASET_PROJECT")
    if override:
        candidate = Path(override)
        return candidate if ExecutionConfig.is_valid_project(candidate) else pytest.skip(
            f"GRASS_DATASET_PROJECT={override} is not a valid project"
        )

    try:
        return Path(ExecutionConfig.detect_dataset().dataset_project)
    except DatasetNotFound as exc:
        pytest.skip(str(exc))


@pytest.fixture
def temp_case_dir(tmp_path: Path) -> Path:
    """An isolated per-case artifact directory."""
    case_dir = tmp_path / "tc_test"
    case_dir.mkdir()
    return case_dir


@pytest.fixture
def permanent_writable(dataset_project: Path) -> bool:
    """Guard against tests silently running against an unguarded mapset.

    The write-bit guard is a permanent property of the provisioned fixture
    (task T024). If it is missing, the very thing this suite exists to detect
    -- mutation of PERMANENT -- could happen unnoticed.
    """
    permanent = dataset_project / "PERMANENT"
    if os.access(permanent, os.W_OK):
        pytest.fail(
            f"{permanent} is writable. The Gate 2 dataset guard (chmod -w) is "
            f"missing; apply it per benchmarks/fixtures/README.md before running "
            f"integration tests, or PERMANENT mutation will go undetected."
        )
    return False


@pytest.fixture(autouse=True)
def apply_slow_marker(request: pytest.FixtureRequest) -> None:
    """Skip anything marked `slow` unless GRASS and the dataset are present.

    Honours GRASS_AGENT_RUN_SLOW=1 to force these on when explicitly wanted.
    """
    if request.node.get_closest_marker("slow") is None:
        return
    if os.environ.get("GRASS_AGENT_RUN_SLOW") == "1":
        return
    if not _grass_available():
        pytest.skip("slow test: GRASS is not available on this host")
    from grass_agent.config import ExecutionConfig, DatasetNotFound

    if os.environ.get("GRASS_DATASET_PROJECT") or _dataset_exists():
        return
    try:
        ExecutionConfig.detect_dataset()
    except DatasetNotFound:
        pytest.skip("slow test: no North Carolina dataset provisioned")


def _dataset_exists() -> bool:
    from grass_agent.config import ExecutionConfig, DatasetNotFound

    try:
        ExecutionConfig.detect_dataset()
        return True
    except DatasetNotFound:
        return False