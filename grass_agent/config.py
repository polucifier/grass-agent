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

# ---------------------------------------------------------------- Feature 004
PIPELINE_LEGACY = "legacy"
PIPELINE_MANUAL_KB = "manual-kb"
PIPELINE_PLANNED = "planned"
PIPELINE_MODES = (PIPELINE_LEGACY, PIPELINE_MANUAL_KB, PIPELINE_PLANNED)

# Constitution v1.4.0: local Ollama models approved for benchmark runs.
APPROVED_PLANNER_MODELS = frozenset(
    {
        "qwen2.5-coder:3b",
        "qwen2.5-coder:7b",
        "qwen2.5-coder:14b",
        "qwen2.5-coder:32b",
    }
)

DEFAULT_NUM_CTX = 8192
DEFAULT_MANUAL_BUDGET_FRACTION = 0.45
MANUAL_BUDGET_WARN_FRACTION = 0.50
MANUAL_BUDGET_MAX_FRACTION = 0.60
DEFAULT_SHORTLIST_K = 12
MIN_SHORTLIST_K = 8
MAX_SHORTLIST_K = 12

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

    # ---- Gate 3: independent repair tiers and the semantic oracle ----------
    # Static (pre-execution) and runtime (execution) repairs are charged
    # independently (FR-001). `max_retries` remains the both-tier shorthand.
    max_static_retries: int = 2
    max_runtime_retries: int = 2
    pilot_suite: str = "benchmarks/benchmark_prompts_pilot10.json"
    pilot_expectations: str = "benchmarks/pilot_expectations.json"
    semantic_query_timeout_s: int = 30
    semantic_probe_timeout_s: int = 60
    semantic_probe_grace_s: int = 5
    # Gate 2 records "gate2"; only run_gate3 overrides this to "gate3". A Gate 2
    # result therefore never matches a Gate 3 resume key (R9).
    harness: str = "gate2"
    semantic_enabled: bool = False

    # ---- Feature 004 additive fields (legacy defaults unchanged) ----------
    pipeline: str = PIPELINE_LEGACY
    num_ctx: int = DEFAULT_NUM_CTX
    manual_context_tokens: int | None = None
    # None means "resolve from the pipeline": True for manual-kb/planned, and
    # the explicit legacy opt-in (default False) otherwise.
    strict_options: bool | None = None
    shortlist_k: int = DEFAULT_SHORTLIST_K
    planner_model: str | None = None
    planner_timeout: int = 60

    # ---------------------------------------------------------------- helpers

    def resolve_manual_budget(self) -> int:
        """Resolved documentation budget.

        An explicit ``manual_context_tokens`` wins; otherwise the budget is
        45% of the context (3686 at 8192, 7372 at 16384).
        """
        if self.manual_context_tokens is not None:
            return self.manual_context_tokens
        return int(DEFAULT_MANUAL_BUDGET_FRACTION * self.num_ctx)

    def effective_strict_options(self) -> bool:
        """Strict closed-enum validation is always on in the new modes."""
        if self.pipeline in (PIPELINE_MANUAL_KB, PIPELINE_PLANNED):
            return True
        return bool(self.strict_options)

    def resolved_planner_model(self) -> str | None:
        """The planner model, defaulting to the synthesis model in planned mode."""
        if self.pipeline != PIPELINE_PLANNED:
            return self.planner_model
        return self.planner_model or self.model

    def config_errors(self) -> list[str]:
        """Human-readable argument errors (exit code 2 when non-empty).

        Kept as a helper rather than raised from the frozen dataclass so the
        CLI can report every problem in one pass.
        """
        errors: list[str] = []
        if self.pipeline not in PIPELINE_MODES:
            errors.append(
                f"--pipeline must be one of {', '.join(PIPELINE_MODES)} "
                f"(got {self.pipeline!r})"
            )
        if self.num_ctx <= 0:
            errors.append("--num-ctx must be > 0")
        if self.manual_context_tokens is not None:
            if self.manual_context_tokens <= 0:
                errors.append("--manual-context-tokens must be > 0")
            elif self.manual_context_tokens > MANUAL_BUDGET_MAX_FRACTION * self.num_ctx:
                errors.append(
                    "--manual-context-tokens must not exceed 60% of --num-ctx "
                    f"({int(MANUAL_BUDGET_MAX_FRACTION * self.num_ctx)})"
                )
        if self.shortlist_k < MIN_SHORTLIST_K or self.shortlist_k > MAX_SHORTLIST_K:
            errors.append(
                f"shortlist_k must be between {MIN_SHORTLIST_K} and "
                f"{MAX_SHORTLIST_K} (got {self.shortlist_k})"
            )
        if self.planner_timeout <= 0:
            errors.append("--planner-timeout must be > 0")
        if self.pipeline == PIPELINE_PLANNED and self.planner_model is not None:
            if self.planner_model not in APPROVED_PLANNER_MODELS:
                errors.append(
                    f"--planner-model {self.planner_model!r} is not in the "
                    f"constitution-approved local stack: "
                    f"{', '.join(sorted(APPROVED_PLANNER_MODELS))}"
                )
        return errors

    def config_warnings(self) -> list[str]:
        """Non-fatal configuration warnings."""
        warnings: list[str] = []
        if self.num_ctx not in (8192, 16384):
            warnings.append(
                f"--num-ctx {self.num_ctx} is not a benchmark value "
                "(supported: 8192, 16384)"
            )
        if self.manual_context_tokens is not None:
            if (
                MANUAL_BUDGET_WARN_FRACTION * self.num_ctx
                < self.manual_context_tokens
                <= MANUAL_BUDGET_MAX_FRACTION * self.num_ctx
            ):
                warnings.append(
                    "--manual-context-tokens is above 50% of --num-ctx; leave "
                    "room for the task, inventory, history, and output"
                )
        return warnings


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

        def _bool(name: str) -> bool | None:
            raw = os.environ.get(name)
            if raw is None or raw.strip() == "":
                return None
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        max_retries = _int("GRASS_MAX_RETRIES", cls.max_retries)
        # Environment precedence for one tier: its own variable > GRASS_MAX_RETRIES
        # > built-in default. CLI flags are applied later by resolve_config().
        base = cls(
            model=os.environ.get("GRASS_OLLAMA_MODEL", cls.model),
            ollama_base_url=os.environ.get("GRASS_OLLAMA_BASE_URL", cls.ollama_base_url),
            max_retries=max_retries,
            max_static_retries=_int("GRASS_MAX_STATIC_RETRIES", max_retries),
            max_runtime_retries=_int("GRASS_MAX_RUNTIME_RETRIES", max_retries),
            timeout_s=_int("GRASS_EXEC_TIMEOUT", cls.timeout_s),
            dataset_project=os.environ.get("GRASS_DATASET_PROJECT") or None,
            fixtures_dir=os.environ.get("GRASS_FIXTURES_DIR", cls.fixtures_dir),
            output_dir=os.environ.get("GRASS_OUTPUT_EXEC_DIR", cls.output_dir),
            knowledge_db=os.environ.get("GRASS_RAG_DB", cls.knowledge_db),
            pilot_suite=os.environ.get("GRASS_PILOT_SUITE", cls.pilot_suite),
            pilot_expectations=os.environ.get(
                "GRASS_PILOT_EXPECTATIONS", cls.pilot_expectations
            ),
            semantic_query_timeout_s=_int(
                "GRASS_SEMANTIC_QUERY_TIMEOUT", cls.semantic_query_timeout_s
            ),
            semantic_probe_timeout_s=_int(
                "GRASS_SEMANTIC_PROBE_TIMEOUT", cls.semantic_probe_timeout_s
            ),
            # ---- Feature 004 environment layer
            pipeline=os.environ.get("GRASS_PIPELINE", cls.pipeline),
            num_ctx=_int("GRASS_NUM_CTX", cls.num_ctx),
            manual_context_tokens=(
                _int("GRASS_MANUAL_CONTEXT_TOKENS", 0)
                if os.environ.get("GRASS_MANUAL_CONTEXT_TOKENS", "").strip()
                else None
            ),
            strict_options=_bool("GRASS_STRICT_OPTIONS"),
            planner_timeout=_int("GRASS_PLANNER_TIMEOUT", cls.planner_timeout),
        )
        return base.with_overrides(**overrides) if overrides else base

    # -------------------------------------------------------------- runtime

    def grass_path(self) -> str:
        return grass_config("path", self.grass_bin)

    def grass_python_path(self) -> str:
        return grass_config("python_path", self.grass_bin)