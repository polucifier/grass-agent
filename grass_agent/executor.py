"""Headless GRASS execution for the Gate 2 harness (FR-003..FR-007, FR-022).

Three verified environment facts shape this module, and violating any of them
produces silently wrong results rather than a loud failure:

1. **The CLI sandbox is not a sandbox.** `grass --tmp-mapset` gives the script
   a writable *default mapset*. A script can call `g.mapset PERMANENT` and
   write there -- VERIFIED: a created raster survived the session. Principle V
   and SC-002 therefore need a filesystem-level guard on PERMANENT, not just
   the temp mapset.

2. **The wrapper destroys signal information.** `grass --exec` reports a child
   SIGSEGV as exit 245, byte-identical to `sys.exit(245)`. Crash detection
   therefore reads the inner wrapper's status file and never the exit code.

3. **Cleanup is `atexit`-based.** SIGTERM and SIGKILL leave `tmp_<uuid>`
   mapsets with `.gislock` behind. A post-run sweep is mandatory (SC-004).

Also verified: `grass --timeout` is a mapset *lock* timeout, not an execution
timeout (an 8s job under `--timeout 2` completed normally). The per-attempt
budget is enforced here via `communicate(timeout=)` plus `killpg`, and is never
forwarded to `grass --timeout`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .classifier import FailureMode, classify, error_excerpt, extract_failing_tool
from .semantic import SemanticResult

# Grace period between SIGTERM and SIGKILL when an attempt is killed.
KILL_GRACE_S = 5

# Languages that would change GRASS error text. German was verified to rewrite
# `ERROR: Raster map <x> not found` into German, and LANGUAGE=en does not
# override it -- which would break every pattern in classifier.py.
_FIXED_LOCALE = "en_US.UTF-8"

_INNER_WRAPPER = Path(__file__).with_name("inner_wrapper.py")
_SEMANTIC_PROBE = Path(__file__).with_name("semantic_probe.py")


class AttemptOutcome(str, Enum):
    """Terminal state of one execution attempt (data-model section 3)."""

    EXECUTED_OK = "executed_ok"
    RUNTIME_FAILED = "runtime_failed"
    CRASHED = "crashed"
    TIMEOUT = "timeout"

    @property
    def consumed_budget(self) -> bool:
        """Whether this outcome costs one unit of the unified retry budget."""
        return self is not AttemptOutcome.EXECUTED_OK

    @property
    def stage(self) -> str:
        return "success" if self is AttemptOutcome.EXECUTED_OK else "runtime"


@dataclass
class ExecutionResult:
    """Everything one execution attempt produced."""

    outcome: AttemptOutcome
    exit_code: int | None = None
    signal_name: str | None = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    failure_mode: FailureMode | None = None
    failing_tool: str | None = None
    error_excerpt: str = ""
    latency_s: float = 0.0
    # Gate 3: maps created by this attempt, and the normalized probe result.
    new_maps: dict = field(
        default_factory=lambda: {"raster": [], "vector": []}
    )
    semantic: SemanticResult | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is AttemptOutcome.EXECUTED_OK


@dataclass
class Executor:
    """Runs scripts in disposable GRASS sessions, one process per attempt."""

    dataset_project: Path
    python_bin: str = "python3"
    grass_bin: str = "grass"
    # Mirrors ExecutionConfig.timeout_s (FR-022). 120s, not 60s: a measured
    # r.slope.aspect over the full NC DEM takes 62-81s, so 60s killed correct
    # scripts. Kept in step with config.py deliberately.
    timeout_s: int = 120
    tmp_root: Path | None = None
    # Added grace for a successful child followed by a bounded probe. The
    # generated script's own bound remains timeout_s.
    semantic_probe_grace_s: int = 5
    _snapshots: list[set[str]] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ launch

    def build_command(self, script: Path, status_path: Path, inner: Path) -> list[str]:
        """Assemble the CLI sandbox invocation.

        `--tmp-mapset <project>/` requires an existing project and creates a
        `tmp_<uuid>` mapset inside it. The trailing slash is what the GRASS docs
        use; set_mapset strips it.
        """
        return [
            self.grass_bin,
            "--tmp-mapset",
            f"{self.dataset_project}/",
            "--exec",
            self.python_bin,
            str(inner),
            str(status_path),
            str(script),
        ]

    def child_env(self, tmp_dir: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Environment for the child session.

        PYTHONPATH is deliberately not set here: GRASS injects its own for the
        `--exec` child, which is *why* a plain `python3` can `import grass.tools`
        (research R2).
        """
        env = dict(os.environ)
        env["LANG"] = _FIXED_LOCALE
        env["LC_ALL"] = _FIXED_LOCALE
        env["LANGUAGE"] = "en"
        env["TMPDIR"] = str(tmp_dir)
        if extra:
            env.update(extra)
        return env

    # --------------------------------------------------------------- integrity

    @staticmethod
    def permanent_hash(dataset_project: Path) -> str:
        """Content hash of the whole PERMANENT tree (SC-002).

        Metadata is excluded: mtimes shift on unrelated reads, and the assertion
        is about content. Raises when the tree is unreadable so a silent skip can
        never masquerade as a pass.
        """
        permanent = dataset_project / "PERMANENT"
        digest = hashlib.sha256()
        if not permanent.is_dir():
            raise FileNotFoundError(f"{permanent} is not a directory")
        for path in sorted(p for p in permanent.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(permanent)).encode())
            try:
                digest.update(hashlib.sha256(path.read_bytes()).digest())
            except OSError as exc:
                raise OSError(f"cannot read {path}: {exc}") from exc
        return digest.hexdigest()

    @staticmethod
    def apply_permanent_guard(dataset_project: Path) -> bool:
        """Drop the write bit on PERMANENT. Idempotent.

        This guard is a permanent property of the provisioned fixture, applied
        once at provisioning time -- nothing reverts it. See
        benchmarks/fixtures/README.md.
        """
        permanent = dataset_project / "PERMANENT"
        if not permanent.is_dir():
            return False
        mode = permanent.stat().st_mode
        if mode & 0o222:
            permanent.chmod(mode & ~0o222)
        return True

    def verify_permanent(self, before: str) -> bool:
        """Assert PERMANENT is byte-for-byte unchanged (FR-005, SC-002)."""
        return self.permanent_hash(self.dataset_project) == before

    # -------------------------------------------------------------------- sweep

    def snapshot_tmp_mapsets(self) -> set[str]:
        """Record the project's `tmp_*` mapsets before an attempt."""
        existing = {p.name for p in self.dataset_project.glob("tmp_*")}
        self._snapshots.append(existing)
        return existing

    def sweep(self, before: set[str], run_start: float) -> list[str]:
        """Delete leaked temp mapsets and report what was removed (SC-004).

        SIGTERM/SIGKILL leave `tmp_<uuid>` mapsets holding `.gislock` behind.
        Only the set difference against the pre-run snapshot is removed -- a
        blanket delete would be unsafe under concurrent runs.

        `run_start` filters by mtime so a stale mapset from an older process is
        left for its owner rather than deleted out from under it.
        """
        removed: list[str] = []
        for path in sorted(self.dataset_project.glob("tmp_*")):
            if path.name in before:
                continue
            try:
                if path.stat().st_mtime < run_start:
                    continue
            except OSError:
                pass
            shutil.rmtree(path, ignore_errors=True)
            if not path.exists():
                removed.append(path.name)
        return removed

    # ---------------------------------------------------------------- execution

    def execute(
        self,
        script: Path,
        workdir: Path,
        semantic_spec: dict | None = None,
        case_id: str | None = None,
    ) -> ExecutionResult:
        """Run one script in a disposable GRASS session.

        When `semantic_spec` is supplied, the in-session wrapper snapshots the
        scratch mapset and runs the read-only probe after a zero-exit child.
        Process-group handling, timeout enforcement, PERMANENT hashing, and the
        write guard are unchanged.
        """
        workdir.mkdir(parents=True, exist_ok=True)
        tmp_dir = self.tmp_root or workdir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        inner = workdir / "inner_wrapper.py"
        shutil.copy2(_INNER_WRAPPER, inner)
        # The wrapper imports the probe from its own directory at run time.
        shutil.copy2(_SEMANTIC_PROBE, workdir / "semantic_probe.py")
        status_path = workdir / "status.json"
        maps_path = workdir / "maps.json"
        semantic_path = workdir / "semantic.json"

        probe_env = {
            "GRASS_AGENT_MAPS_OUT": str(maps_path),
            "GRASS_AGENT_CASE_ID": case_id or "",
        }
        if semantic_spec is not None:
            spec_path = workdir / "semantic_spec.json"
            spec_path.write_text(
                json.dumps(semantic_spec, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            probe_env["GRASS_AGENT_SEMANTIC_SPEC"] = str(spec_path)
            probe_env["GRASS_AGENT_SEMANTIC_OUT"] = str(semantic_path)
            probe_env["GRASS_AGENT_SNAPSHOT_TIMEOUT"] = str(
                semantic_spec.get("query_timeout_s")
                or getattr(self, "semantic_query_timeout_s", 30)
            )

        command = self.build_command(script, status_path, inner)
        started = time.monotonic()
        run_start = time.time()
        self.snapshot_tmp_mapsets()

        # A successful script may be followed by a bounded probe inside the
        # same session. Only that probe gets the grace; the script's own bound
        # is still timeout_s.
        deadline = self.timeout_s
        if semantic_spec is not None:
            deadline += self.semantic_probe_grace_s

        # start_new_session gives the child its own process group. Killing only
        # the `grass` process orphans the Python child and its grandchildren, and
        # communicate() then blocks for the grandchild's full lifetime.
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
            env=self.child_env(tmp_dir, probe_env),
            cwd=str(workdir),
        )

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=deadline)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_group(process)
            try:
                stdout, stderr = process.communicate(timeout=KILL_GRACE_S)
            except subprocess.TimeoutExpired:
                self._kill_group(process, signal.SIGKILL)
                stdout, stderr = process.communicate()
        except BaseException:
            # An operator interrupt (or any harness fault) must not leave a
            # GRASS child and its scratch mapset behind (FR-014, SC-008).
            self._kill_group(process, signal.SIGKILL)
            try:
                process.communicate(timeout=KILL_GRACE_S)
            except (subprocess.TimeoutExpired, OSError):
                pass
            self.sweep(self._snapshots[-1], run_start)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

        latency = time.monotonic() - started
        self.sweep(self._snapshots[-1], run_start)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if not self._snapshots:
            self._snapshots.pop()

        result = self._interpret(
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=timed_out,
            launcher_rc=process.returncode,
            status_path=status_path,
            latency=latency,
        )
        if timed_out:
            # A killed script often produced no diagnostics at all -- only GRASS
            # session chatter. Append the harness's own annotation so the repair
            # prompt says something true instead of quoting the host's bashrc
            # warning. The excerpt is then recomputed from the annotated stream,
            # otherwise it would still carry the pre-annotation extraction.
            annotation = (
                f"GRASS_AGENT: attempt killed after the {self.timeout_s}s "
                f"per-attempt timeout (FR-022). The script did not finish; it "
                f"was not necessarily wrong."
            )
            result.stderr = f"{result.stderr}\n{annotation}\n"
            result.error_excerpt = error_excerpt(result.stdout, result.stderr)

        # ---- Gate 3 evidence. A missing/unparseable probe after a successful
        # execution is a semantic failure, never a harness fault (FR-008e/8g).
        maps_payload = _read_json(maps_path)
        discovered = (maps_payload or {}).get("new_maps") or {}
        result.new_maps = {
            "raster": sorted(discovered.get("raster") or []),
            "vector": sorted(discovered.get("vector") or []),
        }
        if semantic_spec is not None and result.succeeded and not timed_out:
            payload = _read_json(semantic_path)
            if payload is None:
                result.semantic = SemanticResult(
                    evaluated=True,
                    passed=False,
                    case_id=case_id or semantic_spec.get("case_id", ""),
                    new_maps=result.new_maps,
                    error="parse_error",
                )
            else:
                result.semantic = SemanticResult.from_dict(payload)
        return result

    @staticmethod
    def _kill_group(process: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
        """Signal the whole process group, ignoring an already-dead leader."""
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass

    @staticmethod
    def _interpret(
        stdout: str,
        stderr: str,
        timed_out: bool,
        launcher_rc: int | None,
        status_path: Path,
        latency: float,
    ) -> ExecutionResult:
        """Turn captured output into an outcome plus a failure classification.

        The crash signal comes from status.json, never from launcher_rc: a
        child SIGSEGV and `sys.exit(245)` are indistinguishable through
        `grass --exec`.
        """
        status = _read_status(status_path)

        if timed_out:
            outcome = AttemptOutcome.TIMEOUT
        elif status and status.get("status") == "crashed":
            outcome = AttemptOutcome.CRASHED
        elif status is not None:
            code = status.get("exit_code", 0)
            outcome = (
                AttemptOutcome.EXECUTED_OK if code == 0 else AttemptOutcome.RUNTIME_FAILED
            )
        else:
            # No status file: the wrapper never completed. Fall back to the
            # launcher's own exit code, which is trustworthy only for signals
            # delivered to `grass` itself (negative values).
            outcome = (
                AttemptOutcome.EXECUTED_OK
                if launcher_rc == 0
                else AttemptOutcome.RUNTIME_FAILED
            )

        signal_name = status.get("signal_name") if status else None
        if signal_name and not timed_out and launcher_rc is not None and launcher_rc < 0:
            signal_name = signal.Signals(-launcher_rc).name

        result = ExecutionResult(
            outcome=outcome,
            exit_code=(status or {}).get("exit_code", launcher_rc),
            signal_name=signal_name,
            timed_out=timed_out,
            stdout=stdout,
            stderr=stderr,
            latency_s=latency,
        )
        if result.succeeded:
            result.failure_mode = None
        else:
            result.failure_mode = classify(stdout, stderr)
            result.failing_tool = extract_failing_tool(stdout, stderr)
            result.error_excerpt = error_excerpt(stdout, stderr)
        return result


def _read_status(status_path: Path) -> dict | None:
    """Read the inner wrapper's status file, tolerating absence or corruption."""
    try:
        with status_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_json(path: Path) -> dict | None:
    """Read an optional evidence file, tolerating absence or corruption."""
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None