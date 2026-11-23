"""Live semantic pass/fail, staleness, probe faults, and interrupt cleanup (T027).

These tests start real GRASS sessions and are marked `slow`. They skip when
GRASS or the North Carolina dataset is absent.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from grass_agent.executor import AttemptOutcome, Executor

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parent.parent


def _spec(**overrides):
    spec = {
        "schema_version": 1,
        "case_id": "pilot_live",
        "query_timeout_s": 30,
        "probe_timeout_s": 60,
        "outputs": [{"name": "pilot_live", "type": "raster"}],
        "assertions": [
            {"output": "pilot_live", "check": "non_null_count", "min": 1},
            {"output": "pilot_live", "check": "value_range", "min_value": -1, "max": 10},
            {"output": "pilot_live", "check": "mean", "expected": 5.0,
             "tolerance": 0.01},
        ],
    }
    spec.update(overrides)
    return spec


def _run(executor, tmp_path, code, spec, name="live"):
    workdir = tmp_path / f"work_{name}"
    workdir.mkdir(parents=True, exist_ok=True)
    script = workdir / "attempt_1.py"
    script.write_text(textwrap.dedent(code).lstrip(), encoding="utf-8")
    return executor.execute(
        script, workdir, semantic_spec=spec, case_id="pilot_live"
    )


@pytest.fixture
def executor(dataset_project, tmp_path):
    return Executor(
        dataset_project=dataset_project,
        timeout_s=60,
        tmp_root=tmp_path / "session_tmp",
    )


def test_live_script_that_meets_every_assertion_passes(executor, tmp_path):
    result = _run(
        executor,
        tmp_path,
        """
        from grass.tools import Tools
        tools = Tools()
        tools.r_mapcalc(expression="pilot_live = 5")
        """,
        _spec(),
    )
    assert result.succeeded
    assert result.new_maps["raster"] == ["pilot_live"]
    assert result.semantic is not None
    assert result.semantic.evaluated is True
    assert result.semantic.passed is True
    assert result.semantic.error is None
    assert result.semantic.assertion_results
    assert all(a["passed"] for a in result.semantic.assertion_results)


def test_live_all_null_raster_is_an_execution_pass_and_semantic_failure(
    executor, tmp_path
):
    result = _run(
        executor,
        tmp_path,
        """
        from grass.tools import Tools
        tools = Tools()
        tools.r_mapcalc(expression="pilot_live = null()")
        """,
        _spec(),
    )
    assert result.succeeded
    assert result.new_maps["raster"] == ["pilot_live"]
    assert result.semantic is not None
    assert result.semantic.passed is False
    assert result.semantic.error == "no_values"


def test_live_out_of_tolerance_mean_is_a_semantic_failure(executor, tmp_path):
    result = _run(
        executor,
        tmp_path,
        """
        from grass.tools import Tools
        tools = Tools()
        tools.r_mapcalc(expression="pilot_live = 9")
        """,
        _spec(),
    )
    assert result.succeeded
    assert result.semantic is not None
    assert result.semantic.passed is False
    mean = [
        a
        for a in result.semantic.assertion_results
        if a["check"] == "mean"
    ][0]
    assert mean["passed"] is False
    assert mean["expected"] == 5.0
    assert mean["observed"] == 9.0
    assert mean["tolerance"] == 0.01


def test_live_script_that_creates_nothing_has_no_new_maps(executor, tmp_path):
    result = _run(executor, tmp_path, "print('nothing here')\n", _spec())
    assert result.outcome is AttemptOutcome.EXECUTED_OK
    assert result.new_maps == {"raster": [], "vector": []}
    assert result.semantic is not None
    assert result.semantic.passed is False
    assert result.semantic.error == "missing_output"


def test_prior_attempt_map_is_never_credited_to_the_next_attempt(
    executor, tmp_path
):
    """FR-008d: every attempt runs in a fresh temp mapset."""
    first = _run(
        executor,
        tmp_path,
        """
        from grass.tools import Tools
        tools = Tools()
        tools.r_mapcalc(expression="pilot_live = 5")
        raise SystemExit(1)
        """,
        _spec(),
        name="first",
    )
    assert first.outcome is AttemptOutcome.RUNTIME_FAILED
    assert first.new_maps == {"raster": [], "vector": []}

    second = _run(
        executor,
        tmp_path,
        "print('second attempt writes nothing')\n",
        _spec(),
        name="second",
    )
    assert second.succeeded
    assert second.new_maps == {"raster": [], "vector": []}
    assert second.semantic.error == "missing_output"
    assert second.semantic.passed is False


def test_probe_timeout_is_a_semantic_failure_not_a_harness_crash(
    executor, tmp_path
):
    result = _run(
        executor,
        tmp_path,
        """
        from grass.tools import Tools
        tools = Tools()
        tools.r_mapcalc(expression="pilot_live = 5")
        """,
        _spec(probe_timeout_s=0),
    )
    assert result.succeeded
    assert result.semantic is not None
    assert result.semantic.passed is False
    assert result.semantic.error in {"probe_timeout", "query_timeout"}


def test_interrupt_leaves_no_scratch_directory_and_permanent_unchanged(
    dataset_project, tmp_path
):
    before_hash = Executor.permanent_hash(dataset_project)
    before_tmp = {p.name for p in dataset_project.glob("tmp_*")}

    workdir = tmp_path / "interrupt"
    workdir.mkdir()
    script = workdir / "attempt_1.py"
    script.write_text(
        "import time\nprint('hanging', flush=True)\ntime.sleep(300)\n",
        encoding="utf-8",
    )
    driver = tmp_path / "interrupt_driver.py"
    driver.write_text(
        f"""
import os
import signal
import sys
import threading
sys.path.insert(0, {str(REPO_ROOT)!r})
from pathlib import Path
from grass_agent.executor import Executor

def handler(signum, frame):
    raise KeyboardInterrupt()

signal.signal(signal.SIGINT, handler)
threading.Timer(2.0, lambda: os.kill(os.getpid(), signal.SIGINT)).start()

executor = Executor(dataset_project=Path({str(dataset_project)!r}), timeout_s=60)
try:
    executor.execute(Path({str(script)!r}), Path({str(workdir)!r}))
except KeyboardInterrupt:
    print("interrupted")
""",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(driver)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert "interrupted" in completed.stdout, completed.stderr

    assert {p.name for p in dataset_project.glob("tmp_*")} == before_tmp
    assert Executor.permanent_hash(dataset_project) == before_hash


def test_semantic_execution_makes_no_outbound_network_connections(
    executor, tmp_path, monkeypatch
):
    """SC-009: loopback (Ollama) is allowed; anything else fails loudly."""
    import socket

    external = []
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def record(address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if not str(host).startswith("127.") and str(host) not in ("::1", "localhost"):
            external.append(str(host))

    def guard_connect(self, address, *args, **kwargs):
        record(address)
        return real_connect(self, address, *args, **kwargs)

    def guard_create(address, *args, **kwargs):
        record(address)
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket, "create_connection", guard_create)

    _run(
        executor,
        tmp_path,
        """
        from grass.tools import Tools
        tools = Tools()
        tools.r_mapcalc(expression="pilot_live = 5")
        """,
        _spec(),
    )
    assert external == []
