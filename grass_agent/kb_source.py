"""Offline GRASS 8.5 source discovery and XML interface extraction.

Nothing in this module opens a network connection. Sources are resolved from
the installed ``$GISBASE`` tree (Markdown first, HTML fallback) and the XML
interface description is read in a temporary local GRASS session.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MODULE_PREFIXES = ("r.", "r3.", "v.", "d.", "g.", "i.", "db.", "t.", "m.", "p.", "ps.", "q.")
MODULE_NAME_RE = re.compile(
    r"^(?:r|r3|v|d|g|i|db|t|m|p|ps|q)\.[a-z0-9_]+(?:\.[a-z0-9_]+)*$"
)


class XmlUnavailable(Exception):
    """The local GRASS session could not produce XML interface descriptions."""


@dataclass
class ModuleSource:
    """One module's local manual sources."""

    name: str
    markdown_path: str = ""
    html_path: str = ""
    source: str = ""
    content_hash: str = ""

    @property
    def has_manual(self) -> bool:
        return bool(self.markdown_path or self.html_path)


@dataclass
class Inventory:
    """Deterministic module inventory."""

    modules: list[ModuleSource] = field(default_factory=list)
    gisbase: str = ""

    def names(self) -> list[str]:
        return [module.name for module in self.modules]

    def get(self, name: str) -> ModuleSource | None:
        return next((m for m in self.modules if m.name == name), None)


def resolve_gisbase(gisbase: str | None = None, grass_bin: str = "grass") -> Path:
    """Resolve ``$GISBASE`` from the argument, environment, or ``grass --config``."""
    if gisbase:
        return Path(gisbase).expanduser()
    env_value = os.environ.get("GISBASE")
    if env_value:
        return Path(env_value).expanduser()
    try:
        completed = subprocess.run(
            [grass_bin, "--config", "path"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise XmlUnavailable(f"could not run '{grass_bin} --config path': {exc}") from exc
    if completed.returncode != 0:
        raise XmlUnavailable(
            f"'{grass_bin} --config path' failed: {completed.stderr.strip()}"
        )
    value = completed.stdout.strip()
    if not value:
        raise XmlUnavailable("'grass --config path' returned an empty path")
    return Path(value)


def grass_version(grass_bin: str = "grass") -> str:
    """Return the installed GRASS version string (e.g. ``8.5.0``)."""
    completed = subprocess.run(
        [grass_bin, "--version"], capture_output=True, text=True, timeout=30
    )
    text = (completed.stdout or completed.stderr or "").strip()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].upper().startswith("GRASS"):
            return parts[1]
    return parts[1] if (parts := text.split()) and len(parts) > 1 else text


def read_manifest(path: str | Path) -> list[str]:
    """Read the benchmark manifest, ignoring comments and blank lines."""
    manifest = Path(path)
    if not manifest.is_file():
        raise FileNotFoundError(f"required module manifest not found: {manifest}")
    names = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        names.append(stripped)
    return names


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _module_name_from_path(path: Path) -> str:
    return path.stem


def _installed_module_names(gisbase: Path) -> list[str]:
    """Fallback inventory from executable module names in ``$GISBASE/bin``."""
    bin_dir = gisbase / "bin"
    if not bin_dir.is_dir():
        return []
    names = []
    for entry in sorted(bin_dir.iterdir()):
        if not entry.is_file() or not os.access(entry, os.X_OK):
            continue
        name = entry.name
        if name.startswith(MODULE_PREFIXES):
            names.append(name)
    return names


def enumerate_modules(
    gisbase: str | Path | None = None,
    grass_bin: str = "grass",
) -> Inventory:
    """Enumerate local module sources deterministically (sorted by name).

    Markdown is primary; HTML is recorded as a fallback for modules without
    Markdown. Installed executable names are used only when neither docs tree
    exists.
    """
    root = resolve_gisbase(str(gisbase) if gisbase else None, grass_bin)
    markdown_dir = root / "docs" / "mkdocs" / "source"
    html_dir = root / "docs" / "html"

    by_name: dict[str, ModuleSource] = {}
    if markdown_dir.is_dir():
        for path in sorted(markdown_dir.glob("*.md")):
            name = _module_name_from_path(path)
            if not MODULE_NAME_RE.match(name):
                continue
            by_name[name] = ModuleSource(
                name=name,
                markdown_path=str(path),
                source="mkdocs-markdown",
                content_hash=_hash_file(path),
            )

    if html_dir.is_dir():
        for path in sorted(html_dir.glob("*.html")):
            name = _module_name_from_path(path)
            if name in by_name or not MODULE_NAME_RE.match(name):
                continue
            by_name[name] = ModuleSource(
                name=name,
                html_path=str(path),
                source="html",
                content_hash=_hash_file(path),
            )

    if not by_name:
        for name in _installed_module_names(root):
            by_name[name] = ModuleSource(name=name, source="installed")

    return Inventory(
        modules=[by_name[name] for name in sorted(by_name)],
        gisbase=str(root),
    )


_XML_SCRIPT = r"""
import json
import sys

import grass.script.task as task

modules_path, output_path = sys.argv[1], sys.argv[2]
modules = json.load(open(modules_path, encoding="utf-8"))
result = {}
for name in modules:
    try:
        description = task.get_interface_description(name)
    except Exception as exc:  # noqa: BLE001 - record the omission, keep going
        result[name] = {"xml": "", "error": f"{type(exc).__name__}: {exc}"}
        continue
    if isinstance(description, bytes):
        description = description.decode("utf-8", errors="replace")
    result[name] = {"xml": description or "", "error": ""}
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(result, handle)
"""


def load_xml_descriptions(
    modules: list[str],
    gisbase: str | Path | None = None,
    dataset_project: str | None = None,
    grass_bin: str = "grass",
    timeout: int = 600,
) -> dict[str, str]:
    """Return ``name -> XML`` for modules whose interface description is local.

    Raises ``XmlUnavailable`` when the GRASS session itself cannot run. A
    module that simply has no XML is omitted from the mapping; the caller
    decides whether that is fatal (manifest module) or a warning (add-on).
    """
    if not modules:
        return {}
    root = resolve_gisbase(str(gisbase) if gisbase else None, grass_bin)
    with tempfile.TemporaryDirectory(prefix="grass_kb_xml_") as tmp:
        tmp_path = Path(tmp)
        modules_file = tmp_path / "modules.json"
        output_file = tmp_path / "descriptions.json"
        script_file = tmp_path / "extract.py"
        modules_file.write_text(json.dumps(sorted(set(modules))), encoding="utf-8")
        script_file.write_text(_XML_SCRIPT, encoding="utf-8")

        commands = []
        if dataset_project:
            commands.append(
                [
                    grass_bin,
                    "--tmp-mapset",
                    str(Path(dataset_project).expanduser()),
                    "--exec",
                    sys.executable,
                    str(script_file),
                    str(modules_file),
                    str(output_file),
                ]
            )
        # A minimal temporary project is self-contained and never mutates a
        # provisioned dataset; prefer it whenever the CLI supports it.
        commands.insert(
            0,
            [
                grass_bin,
                "--tmp-project",
                "XY",
                "--exec",
                sys.executable,
                str(script_file),
                str(modules_file),
                str(output_file),
            ],
        )

        last_error = ""
        for command in commands:
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env={**os.environ, "GISBASE": str(root)},
                )
            except (OSError, subprocess.SubprocessError) as exc:
                last_error = str(exc)
                continue
            if completed.returncode == 0 and output_file.is_file():
                payload = json.loads(output_file.read_text(encoding="utf-8"))
                return {
                    name: entry.get("xml", "")
                    for name, entry in payload.items()
                    if entry.get("xml")
                }
            last_error = (completed.stderr or completed.stdout or "").strip()

    raise XmlUnavailable(
        "could not obtain interface descriptions from a local GRASS session"
        + (f": {last_error}" if last_error else "")
    )


def build_inventory(
    gisbase: str | Path | None = None,
    grass_bin: str = "grass",
) -> Inventory:
    """Alias kept descriptive for callers that build a full inventory."""
    return enumerate_modules(gisbase, grass_bin)
