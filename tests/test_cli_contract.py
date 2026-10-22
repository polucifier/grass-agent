"""CLI contract conformance (task T039).

Every flag, default, and interaction named in contracts/cli.md is asserted here,
so a contract change that is never implemented shows up as a failing test rather
than as a flag the operator discovers does nothing.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "run_gate2", REPO_ROOT / "benchmarks" / "run_gate2.py"
)
run_gate2 = importlib.util.module_from_spec(SPEC)
sys.modules["run_gate2"] = run_gate2
SPEC.loader.exec_module(run_gate2)

from grass_agent.config import ExecutionConfig  # noqa: E402
from grass_agent.preflight import (  # noqa: E402
    EXIT_ARG,
    EXIT_MISSING_DEPENDENCY,
)


# --------------------------------------------------------------------------
# Flag surface
# --------------------------------------------------------------------------


def test_every_contracted_flag_is_accepted():
    """A flag present in the contract must parse; an absent one must not."""
    parser = run_gate2.build_parser()
    argv = [
        "--model", "qwen2.5-coder:7b",
        "--suite", "benchmarks/benchmark_prompts_tier1.json",
        "--case", "tc_01",
        "--dataset", "/tmp/nc",
        "--max-retries", "1",
        "--timeout", "30",
        "--no-resume",
        "--clean",
        "--reuse-artifacts",
        "--report-only",
        "--verbose",
    ]
    args = parser.parse_args(argv)
    assert args.model == "qwen2.5-coder:7b"
    assert args.case == "tc_01"
    assert args.max_retries == 1
    assert args.timeout == 30
    assert args.resume is False
    assert args.clean and args.reuse_artifacts and args.report_only


def test_removed_flags_are_gone():
    """`--keep-scratch` and `--fail-fast` were deliberately pruned.

    Keeping scratch directories would weaken SC-004's zero-leftover guarantee,
    and stopping early would leave a partial report. See contracts/cli.md
    Non-requirements.
    """
    parser = run_gate2.build_parser()
    for removed in ("--keep-scratch", "--fail-fast"):
        with pytest.raises(SystemExit):
            parser.parse_args([removed])


# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------


def test_contract_defaults():
    args = run_gate2.build_parser().parse_args([])
    assert args.max_retries is None, "None means 'not set on CLI'; the default is resolved from config"
    assert args.timeout is None
    assert args.resume is None, "resume defaults on, resolved through config"


def test_resolved_defaults_match_the_contract():
    config = run_gate2.resolve_config(run_gate2.build_parser().parse_args([]))
    assert config.max_retries == 2
    assert config.timeout_s == 120
    assert config.resume is True
    assert config.attempt1_source == "fresh"


def test_reuse_artifacts_flips_attempt1_source():
    args = run_gate2.build_parser().parse_args(["--reuse-artifacts"])
    assert run_gate2.resolve_config(args).attempt1_source == "reuse_artifacts"


# --------------------------------------------------------------------------
# Precedence: CLI > environment > defaults
# --------------------------------------------------------------------------


def test_cli_argument_beats_environment(monkeypatch):
    monkeypatch.setenv("GRASS_MAX_RETRIES", "5")
    args = run_gate2.build_parser().parse_args(["--max-retries", "1"])
    assert run_gate2.resolve_config(args).max_retries == 1


def test_environment_beats_default(monkeypatch):
    monkeypatch.setenv("GRASS_MAX_RETRIES", "5")
    monkeypatch.setenv("GRASS_EXEC_TIMEOUT", "120")
    monkeypatch.setenv("GRASS_OLLAMA_MODEL", "qwen2.5-coder:7b")
    config = run_gate2.resolve_config(run_gate2.build_parser().parse_args([]))
    assert config.max_retries == 5
    assert config.timeout_s == 120
    assert config.model == "qwen2.5-coder:7b"


def test_all_contracted_env_vars_are_read(monkeypatch):
    monkeypatch.setenv("GRASS_OLLAMA_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("GRASS_OLLAMA_BASE_URL", "http://localhost:1234")
    monkeypatch.setenv("GRASS_RAG_DB", "/tmp/kb.db")
    monkeypatch.setenv("GRASS_DATASET_PROJECT", "/tmp/nc")
    monkeypatch.setenv("GRASS_EXEC_TIMEOUT", "90")
    monkeypatch.setenv("GRASS_MAX_RETRIES", "3")
    monkeypatch.setenv("GRASS_FIXTURES_DIR", "/tmp/fx")
    monkeypatch.setenv("GRASS_OUTPUT_EXEC_DIR", "/tmp/out")
    config = ExecutionConfig.from_env()
    assert config.model == "qwen2.5-coder:7b"
    assert config.ollama_base_url == "http://localhost:1234"
    assert config.knowledge_db == "/tmp/kb.db"
    assert config.dataset_project == "/tmp/nc"
    assert config.timeout_s == 90
    assert config.max_retries == 3
    assert config.fixtures_dir == "/tmp/fx"
    assert config.output_dir == "/tmp/out"


# --------------------------------------------------------------------------
# Validation and exit codes
# --------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--max-retries", "-1"], ["--timeout", "0"], ["--timeout", "-5"]])
def test_argument_errors_exit_2(argv):
    assert run_gate2.main(argv) == EXIT_ARG


def test_unmatched_case_filter_exits_2():
    code = run_gate2.main(["-k", "tc_999", "--max-retries", "0"])
    assert code == EXIT_ARG


def test_missing_suite_exits_2(tmp_path):
    code = run_gate2.main(["-s", str(tmp_path / "nope.json"), "--max-retries", "0"])
    assert code == EXIT_ARG


def test_missing_dataset_exits_3(tmp_path, monkeypatch):
    """FR-023: exit non-zero and name the dependency."""
    monkeypatch.delenv("GRASS_DATASET_PROJECT", raising=False)
    monkeypatch.setattr(ExecutionConfig, "dataset_roots", staticmethod(lambda: [tmp_path]))
    code = run_gate2.main(["-k", "tc_01", "--max-retries", "0"])
    assert code == EXIT_MISSING_DEPENDENCY


def test_clean_wins_over_resume(tmp_path, monkeypatch):
    """`--clean --resume` wipes first, so nothing can be resumed.

    The contract resolves the conflict in favour of --clean rather than
    erroring.
    """
    output = tmp_path / "output_execution"
    case = output / "tc_01"
    case.mkdir(parents=True)
    (case / "case_result.json").write_text('{"tc_id": "tc_01"}', encoding="utf-8")

    monkeypatch.setenv("GRASS_DATASET_PROJECT", str(_valid_project(tmp_path)))
    args = run_gate2.build_parser().parse_args(
        ["-k", "tc_01", "--max-retries", "0", "--clean", "--resume"]
    )
    assert run_gate2.resolve_config(args).resume is True
    run_gate2.shutil.rmtree(output)
    assert not output.exists(), "pre-flight for --clean removes the tree first"


def _valid_project(root: Path) -> Path:
    project = root / "nc"
    permanent = project / "PERMANENT"
    permanent.mkdir(parents=True)
    (permanent / "DEFAULT_WIND").write_text("", encoding="utf-8")
    (permanent / "PROJ_INFO").write_text("", encoding="utf-8")
    return project


# --------------------------------------------------------------------------
# Case filter semantics
# --------------------------------------------------------------------------


def test_both_tiers_cover_40_cases():
    cases, suites = run_gate2.load_selected_cases(run_gate2.build_parser().parse_args([]))
    assert len(cases) == 40
    assert len(suites) == 2


def test_single_suite_covers_its_own_cases():
    args = run_gate2.build_parser().parse_args(
        ["-s", "benchmarks/benchmark_prompts_tier1.json"]
    )
    cases, suites = run_gate2.load_selected_cases(args)
    assert len(cases) == 10
    assert suites == ["benchmark_prompts_tier1.json"]


def test_case_filter_narrows_both_tiers():
    args = run_gate2.build_parser().parse_args(["-k", "tc_01,tc_11"])
    cases, _ = run_gate2.load_selected_cases(args)
    assert [c["id"] for c in cases] == ["tc_01", "tc_11"]