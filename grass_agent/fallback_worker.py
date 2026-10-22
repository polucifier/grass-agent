"""Fallback execution worker for hosts without CLI sandbox support.

Constitution v1.2.0 makes `grass --tmp-mapset <dataset> --exec python3` the
primary execution mechanism, with `grass.script.setup.init()` retained as a
fallback worker. This module implements that fallback.

Why a fallback at all: `grass.script.setup.init()` has no temp-mapset support.
It validates a session and writes a gisrc; it does not create mapsets. Hand-
rolling an ephemeral mapset through it requires a sequence the CLI does not
(research decision D1, research R4):

    1. init(gisdb, location=..., mapset="PERMANENT")
    2. g.mapset -c mapset=tmp_<uuid>     <-- creates the ephemeral mapset
    3. os.remove(<tmp>/.gislock)        <-- MANDATORY, see note below
    4. init(gisdb, location=..., mapset=tmp_<uuid>, lock=True)
    5. ... work ...
    6. shutil.rmtree(<tmp>)

Step 3 is the trap. `g.mapset -c` leaves a `.gislock` in the new mapset, and
the next `init(..., lock=True)` raises `MapsetLockingException` because of it.
Removing the lock by hand is required; skipping it makes the fallback fail on
its first use.

This worker runs *inside* a GRASS session, so `init()` is called only to rebind
to the ephemeral mapset once it exists.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

# Emitted on stdout as JSON so the parent executor can parse a deterministic
# handoff without scraping free-form text.
READY_PREFIX = "GRASS_AGENT_FALLBACK_READY "


def new_mapset_name() -> str:
    """Name for an ephemeral mapset. Matches GRASS's own tmp_<uuid4hex> form."""
    return f"tmp_{uuid.uuid4().hex}"


def create_ephemeral_mapset(session, location: str, mapset: str) -> None:
    """Create `mapset` inside `location` and strip the lock `g.mapset -c` leaves.

    `session` must expose `run_command` from grass.script. Deliberately does not
    use `grass.script.run_command` in *generated* code -- this is harness-side
    infrastructure, not a model-produced script, so the grass.tools-only
    constraint (FR-015, constitution II) does not apply to it.
    """
    import grass.script as gs

    gs.run_command("g.mapset", "-c", mapset=mapset)
    lock = Path(gs.gisenv()["GISDBASE"]) / location / mapset / ".gislock"
    if lock.exists():
        lock.unlink()


def cleanup_ephemeral_mapset(session, location: str, mapset: str) -> None:
    """Remove an ephemeral mapset, tolerating a partially-created one."""
    import grass.script as gs

    path = Path(gs.gisenv()["GISDBASE"]) / location / mapset
    shutil.rmtree(path, ignore_errors=True)


def announce_ready(mapset: str, location: str) -> None:
    """Tell the parent which ephemeral mapset this worker bound to."""
    import json

    print(READY_PREFIX + json.dumps({"mapset": mapset, "location": location}), flush=True)


def assert_permanent_guard(dataset_project: Path) -> None:
    """Fail fast if the PERMANENT write-bit guard is missing.

    Principle V and SC-002 require zero mutation of the persistent mapset. The
    CLI path applies this guard at provisioning time (task T024); the fallback
    path is the one most likely to run on an ad-hoc host, so it verifies rather
    than assuming.
    """
    permanent = dataset_project / "PERMANENT"
    if os.access(permanent, os.W_OK):
        raise PermissionError(
            f"{permanent} is writable. Apply the dataset guard before using the "
            f"fallback worker: chmod -w {permanent}"
        )