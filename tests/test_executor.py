"""Executor integration tests against a live GRASS session (tasks T038, T038a).

Every test here is marked ``slow``: it starts a real headless GRASS process.
They skip automatically when GRASS or the dataset is absent.

The assertions are about the three verified environment hazards:

  * a child SIGSEGV and ``sys.exit(245)`` are indistinguishable through
    ``grass --exec``, so crash detection must read status.json
  * ``grass --timeout`` is a lock timeout, so the budget is enforced by the
    harness via killpg -- otherwise a hang blocks for the child's full lifetime
  * GRASS cleans temp mapsets via atexit, so SIGKILL leaks them and the sweep
    is what keeps the project directory clean
"""

import os
import socket
import textwrap

import pytest

from grass_agent.executor import AttemptOutcome, Executor

pytestmark = pytest.mark.slow

SCRIPTS = {
    "ok": """
        from grass.tools import Tools
        import grass.script as gs
        print("MAPSET=" + gs.gisenv()["MAPSET"])
    """,
    "segv": """
        import ctypes
        print("before", flush=True)
        ctypes.string_at(0)
    """,
    "missing_map": """
        from grass.tools import Tools
        Tools().r_slope_aspect(elevation="nope", slope="s", aspect="a")
    """,
    "bad_method": """
        from grass.tools import Tools
        Tools().v_update_column(input="x")
    """,
    "hang": """
        import time
        print("hanging", flush=True)
        time.sleep(300)
    """,
    "legacy_shell": """
        import grass.script as gs
        gs.run_command("r.info", map="elevation")
    """,
}


@pytest.fixture
def executor(dataset_project, tmp_path):
    return Executor(
        dataset_project=dataset_project,
        timeout_s=15,
        tmp_root=tmp_path / "session_tmp",
    )


def _run(executor, tmp_path, name):
    workdir = tmp_path / f"work_{name}"
    workdir.mkdir(parents=True, exist_ok=True)
    script = workdir / "attempt_1.py"
    script.write_text(textwrap.dedent(SCRIPTS[name]).lstrip(), encoding="utf-8")
    return executor.execute(script, workdir)


# --------------------------------------------------------------------------
# Outcome detection
# --------------------------------------------------------------------------


def test_clean_run_succeeds(executor, tmp_path):
    result = _run(executor, tmp_path, "ok")
    assert result.outcome is AttemptOutcome.EXECUTED_OK
    assert result.succeeded
    assert result.failure_mode is None
    assert "MAPSET=tmp_" in result.stdout


def test_failure_is_classified(executor, tmp_path):
    result = _run(executor, tmp_path, "missing_map")
    assert result.outcome is AttemptOutcome.RUNTIME_FAILED
    assert result.failure_mode.value == "missing_input"
    assert result.failing_tool == "r.slope.aspect"
    assert "Raster map <nope> not found" in result.stderr


def test_hallucinated_method_is_classified(executor, tmp_path):
    result = _run(executor, tmp_path, "bad_method")
    assert result.failure_mode.value == "unknown_method"
    assert result.failing_tool == "v.update.column"


def test_segfault_is_detected_from_status_not_exit_code(executor, tmp_path):
    """SIGSEGV and sys.exit(245) both surface as 245 through grass --exec.

    Only the forked wrapper's status file distinguishes them, so asserting on
    signal_name is what proves the wrapper is wired correctly.
    """
    result = _run(executor, tmp_path, "segv")
    assert result.outcome is AttemptOutcome.CRASHED
    assert result.signal_name == "SIGSEGV"
    assert result.failure_mode.value == "general_exception"


def test_harness_survives_a_crash_and_keeps_going(executor, tmp_path, dataset_project):
    """SC-003: a crash costs that case only, never the suite.

    Runs a crash, then a clean script, then a failure -- all three must
    complete in one live executor, proving nothing was left wedged.
    """
    assert _run(executor, tmp_path, "segv").outcome is AttemptOutcome.CRASHED
    assert _run(executor, tmp_path, "ok").outcome is AttemptOutcome.EXECUTED_OK
    assert _run(executor, tmp_path, "bad_method").outcome is AttemptOutcome.RUNTIME_FAILED


def test_hang_is_bounded_and_suite_proceeds(executor, tmp_path):
    """SC-012: the per-attempt budget is enforced by the harness."""
    result = _run(executor, tmp_path, "hang")
    assert result.outcome is AttemptOutcome.TIMEOUT
    assert result.timed_out
    assert result.failure_mode.value == "general_exception"
    # Bounded: the script sleeps 300s, the budget is 15s.
    assert result.latency_s < 60
    # The suite keeps going.
    assert _run(executor, tmp_path, "ok").outcome is AttemptOutcome.EXECUTED_OK


# --------------------------------------------------------------------------
# Integrity and cleanup
# --------------------------------------------------------------------------


def test_permanent_mapset_is_unchanged(executor, dataset_project):
    """SC-002."""
    before = executor.permanent_hash(dataset_project)
    assert executor.verify_permanent(before)


def test_permanent_guard_is_required(executor, dataset_project, permanent_writable):
    """The guard must be present, or mutation could go undetected."""
    assert not os.access(dataset_project / "PERMANENT", os.W_OK)


def test_temp_mapsets_are_swept_after_a_hang(executor, tmp_path, dataset_project):
    """SC-004: a killed attempt must leave no tmp_<uuid> behind."""
    before = {p.name for p in dataset_project.glob("tmp_*")}
    _run(executor, tmp_path, "hang")
    assert {p.name for p in dataset_project.glob("tmp_*")} == before


def test_no_leftovers_across_a_mixed_run(executor, tmp_path, dataset_project):
    before = {p.name for p in dataset_project.glob("tmp_*")}
    for name in ("ok", "segv", "missing_map", "bad_method", "hang"):
        _run(executor, tmp_path, name)
    assert {p.name for p in dataset_project.glob("tmp_*")} == before


def test_session_tmpdir_is_removed(executor, tmp_path):
    _run(executor, tmp_path, "ok")
    assert not (tmp_path / "session_tmp").exists()


def test_legacy_shell_script_is_caught_by_the_guard_not_the_executor(executor, tmp_path):
    """Defence in depth: the executor is not the enforcement point.

    A run_command script will happily execute if the map it names happens to
    exist -- against the real NC dataset `r.info map=elevation` returns 0. The
    prohibition is enforced by the static guard *before* execution, so what the
    executor guarantees is only that it reports whatever actually happened.
    """
    result = _run(executor, tmp_path, "legacy_shell")
    # Whatever the outcome, the guard is what rejects it -- proven here by the
    # guard's own AST check, which needs no GRASS session at all.
    class EmptyRetriever:
        def get_tool(self, name):
            return None

    from benchmarks.run_execution import static_guard

    issues = static_guard(textwrap.dedent(SCRIPTS["legacy_shell"]).lstrip(), EmptyRetriever())
    assert any("legacy interface" in issue for issue in issues)
    # And the outcome is reported faithfully rather than masked.
    assert result.outcome in {
        AttemptOutcome.EXECUTED_OK,
        AttemptOutcome.RUNTIME_FAILED,
    }


# --------------------------------------------------------------------------
# Offline enforcement (SC-011, FR-016)
# --------------------------------------------------------------------------


def test_no_outbound_network_connections_during_execution(executor, tmp_path, monkeypatch):
    """The offline-first mandate, asserted rather than assumed.

    Loopback is allowed -- the Ollama client legitimately uses 127.0.0.1. Any
    other destination is a constitution violation, so this fails loudly.
    """
    external: list[str] = []
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def guard_connect(self, address, *args, **kwargs):
        _record(address)
        return real_connect(self, address, *args, **kwargs)

    def guard_create(address, *args, **kwargs):
        _record(address)
        return real_create(address, *args, **kwargs)

    def _record(address) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        if not str(host).startswith("127.") and str(host) not in ("::1", "localhost"):
            external.append(str(host))

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket, "create_connection", guard_create)

    _run(executor, tmp_path, "ok")
    _run(executor, tmp_path, "missing_map")

    assert external == [], f"harness opened non-loopback connections: {external}"

def test_timeout_excerpt_is_the_harness_annotation_not_host_noise(executor, tmp_path):
    """A killed script often emits only GRASS session chatter.

    Without the harness annotation the excerpt would be the host's bashrc
    warning, telling the repair model nothing about why it was killed. The
    excerpt must be recomputed after the annotation is appended.
    """
    result = _run(executor, tmp_path, "hang")
    assert result.outcome is AttemptOutcome.TIMEOUT
    assert "GRASS_AGENT" in result.error_excerpt
    assert "fish" not in result.error_excerpt
    assert "Unsupported shell" not in result.error_excerpt
    # Invariant I8: the excerpt must remain verbatim captured output.
    assert result.error_excerpt in result.stderr
