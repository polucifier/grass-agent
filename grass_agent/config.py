"""Execution configuration for the Gate 2 harness.

Distinct from the repository-root ``config.py``, which is Gate 1's
``GenerationConfig`` and is imported unchanged. This module carries settings
for the execution harness only.

GRASS paths are resolved at runtime via ``grass --config`` rather than
hard-coded, so the harness works on any GRASS prefix (research decision D2).
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

# Standard North Carolina sample project directory names. The `_grass8` archive
# 404s upstream; `nc_basic_spm_grass7` is the live package and loads in 8.5.
NC_PROJECT_NAMES = ("nc_basic_spm_grass8", "nc_spm_08_grass7")

# Roots searched, in order, when no dataset path is supplied.
DEFAULT_DATASET_ROOTS = ("GISDBASE", "GRASSDATA", "~/grassdata", "./grassdata")


class DatasetNotFound(Exception):
    """No usable North Carolina project could be located.

    Carries the roots that were searched so pre-flight can name them in its
    exit-3 message (FR-023).
    """

    def __init__(self, roots: list[str]):
        self.roots = roots
        super().__init__(
            "No North Carolina dataset found. Searched: "
            + ", ".join(roots)
            + f" (expected one of: {', '.join(NC_PROJECT_NAMES)}). "
            "Provision it manually -- see benchmarks/fixtures/README.md."
        )


class GrassUnavailable(Exception):
    """GRASS is not installed, or `grass --config` failed."""


def grass_config(param: str, grass_bin: str = "grass") -> str:
    """Return a `grass --config <param>` value, resolved at runtime."""
    try:
        result = subprocess.run(
            [grass_bin, "--config", param],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GrassUnavailable(f"could not run '{grass_bin} --config {param}': {exc}") from exc
    if result.returncode != 0:
        raise GrassUnavailable(
            f"'{grass_bin} --config {param}' failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


@dataclass(frozen=True)
class ExecutionConfig:
    """Immutable settings for one harness invocation."""

    model: str = "qwen2.5-coder:3b"
    ollama_base_url: str = "http://localhost:11434"
    max_retries: int = 2
    # 120s, not 60s. A single `r.slope.aspect` run over the full NC elevation
    # DEM was measured at 62-81s depending on host load, so a 60s bound killed
    # legitimate, correct heavy raster work and recorded it as a timeout -- a
    # false failure that healing cannot repair. 120s covers the measured worst
    # case with headroom while still bounding a hung or interactive script.
    timeout_s: int = 120
    attempt1_source: str = "fresh"  # "fresh" | "reuse_artifacts"
    resume: bool = True
    dataset_project: str | None = None
    fixtures_dir: str = "benchmarks/fixtures"
    output_dir: str = "benchmarks/output_execution"
    report_path: str = "benchmarks/execution_report.md"
    knowledge_db: str = "data/grass_knowledge.db"
    reuse_artifacts_dir: str = "benchmarks/output"
    grass_bin: str = "grass"
    python_bin: str = "python3"
    case_filter: tuple[str, ...] = ()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def is_valid_project(path: Path | str) -> bool:
        """True when `path` is a GRASS project with a usable PERMANENT mapset.

        A project is valid when PERMANENT exists and holds DEFAULT_WIND and
        PROJ_INFO -- the two files GRASS itself requires (research R1).
        """
        p = Path(path)
        permanent = p / "PERMANENT"
        return (
            permanent.is_dir()
            and (permanent / "DEFAULT_WIND").is_file()
            and (permanent / "PROJ_INFO").is_file()
        )

    @staticmethod
    def dataset_roots() -> list[Path]:
        """Roots to search for a dataset, in the contracted order."""
        roots: list[Path] = []
        for key in DEFAULT_DATASET_ROOTS:
            if key.startswith("~"):
                roots.append(Path(key).expanduser())
            elif key.startswith("./"):
                roots.append(Path(key).resolve())
            else:
                value = os.environ.get(key)
                if value:
                    roots.append(Path(value).expanduser())
        return roots

    @staticmethod
    def detect_dataset(grass_bin: str = "grass") -> "ExecutionConfig":
        """Return a config with `dataset_project` auto-detected.

        Raises DatasetNotFound carrying every root searched, so the caller can
        report all of them rather than only the last one tried.
        """
        searched: list[str] = []
        for root in ExecutionConfig.dataset_roots():
            searched.append(str(root))
            if not root.is_dir():
                continue
            for name in NC_PROJECT_NAMES:
                candidate = root / name
                if ExecutionConfig.is_valid_project(candidate):
                    return ExecutionConfig(dataset_project=str(candidate), grass_bin=grass_bin)
            # Accept any project directory in the root that looks valid, even if
            # it is not one of the two standard names.
            for child in sorted(root.iterdir()):
                if child.is_dir() and ExecutionConfig.is_valid_project(child):
                    return ExecutionConfig(dataset_project=str(child), grass_bin=grass_bin)
        raise DatasetNotFound(searched)

    @property
    def dataset_path(self) -> Path:
        if self.dataset_project is None:
            raise DatasetNotFound([str(r) for r in self.dataset_roots()])
        return Path(self.dataset_project)

    def with_overrides(self, **kwargs) -> "ExecutionConfig":
        """Return a copy with fields replaced. CLI args win over env vars."""
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})

    # ------------------------------------------------------------- from_env()

    @classmethod
    def from_env(cls, **overrides) -> "ExecutionConfig":
        """Build a config from `GRASS_*` environment variables.

        Mirrors the Gate 1 ``GenerationConfig.from_env()`` convention at
        ``config.py:15-23``. Precedence, lowest to highest:
        built-in defaults < environment variables < **overrides (CLI args).
        """

        def _int(name: str, fallback: int) -> int:
            raw = os.environ.get(name)
            if raw is None or raw.strip() == "":
                return fallback
            try:
                return int(raw)
            except ValueError:
                return fallback

        base = cls(
            model=os.environ.get("GRASS_OLLAMA_MODEL", cls.model),
            ollama_base_url=os.environ.get("GRASS_OLLAMA_BASE_URL", cls.ollama_base_url),
            max_retries=_int("GRASS_MAX_RETRIES", cls.max_retries),
            timeout_s=_int("GRASS_EXEC_TIMEOUT", cls.timeout_s),
            dataset_project=os.environ.get("GRASS_DATASET_PROJECT") or None,
            fixtures_dir=os.environ.get("GRASS_FIXTURES_DIR", cls.fixtures_dir),
            output_dir=os.environ.get("GRASS_OUTPUT_EXEC_DIR", cls.output_dir),
            knowledge_db=os.environ.get("GRASS_RAG_DB", cls.knowledge_db),
        )
        return base.with_overrides(**overrides) if overrides else base

    # -------------------------------------------------------------- runtime

    def grass_path(self) -> str:
        return grass_config("path", self.grass_bin)

    def grass_python_path(self) -> str:
        return grass_config("python_path", self.grass_bin)