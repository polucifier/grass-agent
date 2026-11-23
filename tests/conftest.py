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


# --------------------------------------------------------------------------
# Feature 004 shared test helpers (T003)
# --------------------------------------------------------------------------


class FakeOllamaProvider:
    """Deterministic local provider double for offline pipeline tests.

    It implements the same three methods the real provider exposes, records
    every call, and returns a caller-supplied response per call (the last
    response repeats). Token counters are synthetic but non-zero so accounting
    paths are exercised.
    """

    def __init__(self, responses=None, embedding=None, prompt_tokens=11, completion_tokens=7):
        self.model = "fake:model"
        self.embedding_model = "fake-embed"
        self.base_url = "http://localhost:11434"
        self.last_stats = {"prompt_tokens": 0, "completion_tokens": 0}
        self.responses = list(responses or ["print('ok')"])
        self.embedding = list(embedding or [0.01] * 8)
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls: list[dict] = []
        self.raise_timeout = False

    def _respond(self, messages, options=None):
        self.calls.append({"messages": messages, "options": options})
        if self.raise_timeout:
            raise TimeoutError("planner timeout")
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        text = self.responses[index]
        stats = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }
        self.last_stats = stats
        return text, stats

    def chat(self, messages, options=None):
        return self._respond(messages, options)[0]

    def chat_with_stats(self, messages, options=None):
        return self._respond(messages, options)

    def generate_embeddings(self, text):
        return list(self.embedding)


class FakeRetriever:
    """In-memory retriever double matching the real public surface."""

    def __init__(self, docs=None, shortlist=None):
        self.docs = {doc.name: doc for doc in (docs or [])}
        self.shortlist = shortlist
        self.retrieve_calls: list[tuple[str, int]] = []
        self.shortlist_calls: list[int] = []

    def get_tool(self, name):
        return self.docs.get(name)

    def get_manual(self, name):
        return self.docs.get(name)

    def retrieve(self, query, query_embedding, k=5):
        self.retrieve_calls.append((query, k))
        if self.shortlist is not None:
            return list(self.shortlist[:k])
        return list(self.docs.values())[:k]

    def retrieve_shortlist(self, query, query_embedding, shortlist_k=12, embedding_model=""):
        from rag_retriever import CandidateShortlist

        self.shortlist_calls.append(shortlist_k)
        docs = self.retrieve(query, query_embedding, k=shortlist_k)
        return CandidateShortlist(
            query=query,
            candidates=docs,
            shortlist_shortfall=len(docs) < 8,
            shortlist_k=shortlist_k,
            embedding_model=embedding_model,
        )

    def close(self):
        pass


@pytest.fixture
def fake_provider():
    return FakeOllamaProvider()


@pytest.fixture
def fake_retriever():
    return FakeRetriever()


@pytest.fixture
def kb_db_factory(tmp_path):
    """Return a callable that creates a temporary Feature 004 SQLite KB."""
    counter = {"n": 0}

    def _make(records=(), legacy=False):
        from grass_agent import kb_schema

        counter["n"] += 1
        path = tmp_path / f"kb_{counter['n']}.db"
        conn = kb_schema.open_database(str(path), load_vectors=not legacy)
        if legacy:
            conn.execute(
                "CREATE TABLE tools ("
                "rowid INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,"
                "category TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',"
                "signature TEXT NOT NULL DEFAULT '', example TEXT NOT NULL DEFAULT '',"
                "params_json TEXT NOT NULL DEFAULT '{}')"
            )
            for record in records:
                conn.execute(
                    "INSERT INTO tools (name, category, description, signature, example, params_json) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        record["name"],
                        record.get("category", record["name"].split(".")[0]),
                        record.get("description", ""),
                        record.get("signature", ""),
                        record.get("example", ""),
                        __import__("json").dumps(record.get("params", {})),
                    ),
                )
            conn.commit()
        else:
            kb_schema.ensure_schema(conn)
            for record in records:
                kb_schema.upsert_tool(conn, record)
            conn.commit()
        return path, conn

    return _make


@pytest.fixture
def socket_guard(monkeypatch):
    """Block every outbound TCP connection and record attempted peers.

    AF_UNIX is left alone: it is local IPC, not network access. Tests assert
    the recorded list is empty to prove the code path is offline.
    """
    import socket

    attempts: list[tuple] = []
    original = socket.socket.connect

    def guarded_connect(self, address):
        if self.family == socket.AF_UNIX:
            return original(self, address)
        attempts.append(address)
        raise AssertionError(f"outbound network connection attempted: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return attempts
