"""Gate 3 CLI surface, budget precedence, and pre-flight failures (T039, T044).

The contract keeps `--max-retries` as a both-tier shorthand, gives tier flags
precedence over it, and requires a named dependency on every pre-flight failure.
"""

import argparse
from pathlib import Path

import pytest

from benchmarks import run_gate2, run_gate3
from grass_agent.config import ExecutionConfig
from grass_agent.preflight import (
    EXIT_ARG,
    EXIT_MISSING_DEPENDENCY,
    MissingDependency,
    PreflightReport,
)


def _gate3(*argv):
    return run_gate3.build_parser().parse_args(list(argv))


def _resolved(*argv):
    return run_gate2.resolve_config(_gate3(*argv))


# --------------------------------------------------------------------------
# Flag surface
# --------------------------------------------------------------------------


def test_tier_flags_parse():
    args = _gate3("--max-static-retries", "1", "--max-runtime-retries", "3")
    assert args.max_static_retries == 1
    assert args.max_runtime_retries == 3


def test_gate3_semantic_defaults_on():
    assert _gate3().semantic is True
    assert _gate3("--no-semantic").semantic is False


def test_negative_tier_budgets_exit_2(capsys):
    assert run_gate3.main(["--max-static-retries", "-1"]) == EXIT_ARG
    assert "--max-static-retries" in capsys.readouterr().err
    assert run_gate3.main(["--max-runtime-retries", "-1"]) == EXIT_ARG
    assert "--max-runtime-retries" in capsys.readouterr().err
    assert run_gate2.main(["--max-static-retries", "-1"]) == EXIT_ARG


def test_non_integer_tier_budget_exits_2():
    with pytest.raises(SystemExit) as exc:
        _gate3("--max-static-retries", "nope")
    assert exc.value.code == 2


# --------------------------------------------------------------------------
# Budget precedence
# --------------------------------------------------------------------------


def test_max_retries_sets_both_tiers():
    config = _resolved("--max-retries", "3")
    assert config.max_static_retries == 3
    assert config.max_runtime_retries == 3


def test_tier_flag_overrides_the_shorthand():
    config = _resolved("--max-retries", "3", "--max-static-retries", "1")
    assert config.max_static_retries == 1
    assert config.max_runtime_retries == 3


def test_environment_tier_vars_apply(monkeypatch):
    monkeypatch.setenv("GRASS_MAX_STATIC_RETRIES", "4")
    monkeypatch.setenv("GRASS_MAX_RUNTIME_RETRIES", "5")
    monkeypatch.delenv("GRASS_MAX_RETRIES", raising=False)
    config = _resolved()
    assert config.max_static_retries == 4
    assert config.max_runtime_retries == 5


def test_max_retries_env_is_the_tier_fallback(monkeypatch):
    monkeypatch.setenv("GRASS_MAX_RETRIES", "1")
    monkeypatch.delenv("GRASS_MAX_STATIC_RETRIES", raising=False)
    monkeypatch.delenv("GRASS_MAX_RUNTIME_RETRIES", raising=False)
    config = _resolved()
    assert config.max_static_retries == 1
    assert config.max_runtime_retries == 1


def test_cli_shorthand_beats_tier_environment(monkeypatch):
    monkeypatch.setenv("GRASS_MAX_RETRIES", "1")
    config = _resolved("--max-retries", "3", "--max-runtime-retries", "4")
    assert config.max_static_retries == 3
    assert config.max_runtime_retries == 4


def test_gate2_parser_defaults_are_unchanged():
    args = run_gate2.build_parser().parse_args([])
    assert args.max_retries is None
    assert run_gate2.resolve_config(args).max_retries == 2


# --------------------------------------------------------------------------
# Option interactions
# --------------------------------------------------------------------------


def test_all_conflicts_with_pilot_suite(capsys):
    code = run_gate3.main(
        ["--all", "--pilot-suite", "benchmarks/benchmark_prompts_pilot10.json"]
    )
    assert code == EXIT_ARG
    assert "mutually exclusive" in capsys.readouterr().err


def test_report_only_conflicts_with_clean(capsys):
    code = run_gate3.main(["--report-only", "--clean"])
    assert code == EXIT_ARG
    assert "cannot be combined" in capsys.readouterr().err


def test_validate_pilot_wins_over_execution_flags(monkeypatch):
    called = {}

    def fake_validate(config, suite, expectations):
        called["hit"] = True
        return 0

    monkeypatch.setattr(run_gate3, "validate_pilot", fake_validate)
    code = run_gate3.main(["--validate-pilot", "--clean", "--all"])
    assert code == 0
    assert called.get("hit") is True


def test_case_filter_applies_within_the_selected_pilot():
    args = run_gate3.build_parser().parse_args(
        ["-k", "pilot_tc_05", "--pilot-suite",
         "benchmarks/benchmark_prompts_pilot10.json"]
    )
    args.suite = "benchmarks/benchmark_prompts_pilot10.json"
    cases, suites = run_gate2.load_selected_cases(args)
    assert [c["id"] for c in cases] == ["pilot_tc_05"]
    assert suites == ["benchmark_prompts_pilot10.json"]


def test_case_filter_applies_within_all_40(monkeypatch):
    args = run_gate3.build_parser().parse_args(["-k", "tc_01,tc_11", "--all"])
    args.suite = None
    cases, _ = run_gate2.load_selected_cases(args)
    assert [c["id"] for c in cases] == ["tc_01", "tc_11"]


# --------------------------------------------------------------------------
# Pre-flight exit 3 with a named dependency
# --------------------------------------------------------------------------


def _patch_preflight(monkeypatch, name, detail="unavailable"):
    report = PreflightReport(
        ok=False,
        checked=[name],
        failures=[MissingDependency(name, detail)],
        dataset_project=Path("/tmp/nc"),
    )
    monkeypatch.setattr(run_gate3, "run_preflight", lambda *a, **k: report)


@pytest.mark.parametrize(
    "name",
    [
        "GRASS installation",
        "GRASS sample dataset",
        "local model service",
        "knowledge base",
        "benchmark fixtures",
    ],
)
def test_preflight_failure_exits_3_naming_the_dependency(monkeypatch, capsys, name):
    _patch_preflight(monkeypatch, name)
    code = run_gate3.main(["-k", "pilot_tc_01", "--no-semantic"])
    assert code == EXIT_MISSING_DEPENDENCY
    assert name in capsys.readouterr().err
