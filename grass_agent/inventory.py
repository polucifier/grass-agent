"""Grounding the repair prompt with the maps that actually exist.

The healing loop cannot fix ``missing_input`` on its own. FR-012's four
elements name the task, the failing script, the error, and the tool docs --
none of which say *which maps the dataset contains*. A model that invents
``bathymetry`` therefore receives an error reading "Raster map <bathymetry>
not found" and has nothing to learn from: it cannot know that ``lakes`` is the
map it wanted. Measured over a full 40-case run, 46% of all failed attempts
were ``missing_input``, and ``missing_input -> missing_input`` was the single
most common transition (32 occurrences) -- a failure mode that is
information-theoretically unhealable without an inventory channel.

This module supplies that channel. The inventory is read from the project's
``PERMANENT`` mapset on disk, which is the source of truth GRASS itself uses
and requires no running session:

* rasters live under ``PERMANENT/cellhd/<name>``
* vectors live under ``PERMANENT/vector/<name>/``

A GRASS ``g.list`` fallback exists for layouts the filesystem reader does not
recognise, but the filesystem path is primary: it is fast, deterministic, and
testable without a GRASS installation.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# A prompt block is only useful while it stays small. These bounds keep the
# inventory from crowding out the error text and the failing script, which are
# what the model most needs to fix.
MAX_MAPS_PER_KIND = 80

INVENTORY_HEADING = "### Available Dataset Maps"

_GROUNDING_INSTRUCTION = (
    "These are the ONLY maps that exist in this dataset. Use exactly these "
    "names. If the task refers to a map that is not listed here, choose the "
    "closest listed map and say so in a comment -- never invent a map name."
)


@dataclass(frozen=True)
class MapInventory:
    """The rasters and vectors available in the target dataset."""

    rasters: tuple[str, ...] = ()
    vectors: tuple[str, ...] = ()
    truncated: bool = field(default=False)

    def is_empty(self) -> bool:
        return not (self.rasters or self.vectors)

    def format_block(self) -> str:
        """Render the ``### Available Dataset Maps`` prompt block.

        Returns an empty string when no maps are known, so callers can append
        it unconditionally without emitting an empty heading.
        """
        if self.is_empty():
            return ""
        lines = [INVENTORY_HEADING, _GROUNDING_INSTRUCTION, ""]
        lines.append(
            f"Available Rasters: [{', '.join(self.rasters)}]"
            if self.rasters
            else "Available Rasters: [none]"
        )
        lines.append(
            f"Available Vectors: [{', '.join(self.vectors)}]"
            if self.vectors
            else "Available Vectors: [none]"
        )
        if self.truncated:
            lines.append(
                "(list truncated; more maps exist than are shown)"
            )
        return "\n".join(lines)


def _names_in(directory: Path, *, as_directory: bool) -> list[str]:
    """Sorted child names, tolerating absence and unreadable entries."""
    if not directory.is_dir():
        return []
    names: list[str] = []
    for child in directory.iterdir():
        try:
            if as_directory and not child.is_dir():
                continue
            if not as_directory and child.is_dir():
                # A directory where a file is expected (or vice versa) is not a
                # map in this layout; skip rather than guess.
                continue
        except OSError:
            continue
        if child.name.startswith("."):
            continue
        names.append(child.name)
    return sorted(set(names))


def read_inventory(dataset_project: Path | str) -> MapInventory:
    """Read the map inventory from a project's ``PERMANENT`` mapset.

    Never raises: grounding is an enhancement, and a failure to read the
    inventory must not break the healing loop. An unreadable dataset yields an
    empty inventory, and the repair prompt simply omits the block.
    """
    project = Path(dataset_project)
    permanent = project / "PERMANENT"
    try:
        rasters = _names_in(permanent / "cellhd", as_directory=False)
        # 3D rasters (raster_3d) live under grid3/ and are callable by name too.
        rasters = sorted(set(rasters) | set(_names_in(permanent / "grid3", as_directory=True)))
        vectors = _names_in(permanent / "vector", as_directory=True)
    except OSError:
        return MapInventory()

    truncated = False
    if len(rasters) > MAX_MAPS_PER_KIND:
        rasters, truncated = rasters[:MAX_MAPS_PER_KIND], True
    if len(vectors) > MAX_MAPS_PER_KIND:
        vectors, truncated = vectors[:MAX_MAPS_PER_KIND], True
    return MapInventory(rasters=tuple(rasters), vectors=tuple(vectors), truncated=truncated)


def query_with_grass(
    dataset_project: Path | str, grass_bin: str = "grass", timeout: int = 60
) -> MapInventory:
    """Fallback inventory via ``g.list`` in a throwaway GRASS session.

    Used only when the filesystem reader finds nothing -- for example a project
    whose mapsets are laid out unusually. A failure here is not fatal; the
    caller falls back to an empty inventory.
    """

    def _list(kind: str) -> tuple[str, ...]:
        try:
            completed = subprocess.run(
                [
                    grass_bin,
                    "--tmp-mapset",
                    f"{Path(dataset_project)}/",
                    "--exec",
                    "g.list",
                    f"type={kind}",
                    "mapset=PERMANENT",
                    "-m",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                errors="replace",
            )
        except (OSError, subprocess.SubprocessError):
            return ()
        if completed.returncode != 0:
            return ()
        names = set()
        for line in completed.stdout.splitlines():
            label = line.strip().split("@", 1)[0]
            if label:
                names.add(label)
        return tuple(sorted(names))

    return MapInventory(rasters=_list("raster"), vectors=_list("vector"))
