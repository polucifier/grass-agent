"""Additive SQLite schema for the Feature 004 knowledge base.

The legacy ``tools``/``tools_vec`` tables are preserved. New columns are
appended to ``tools`` and three normalised tables plus ``db_meta`` are added.
Every migration is idempotent: running it twice is a no-op, and unchanged
records keep stable content hashes (KB5, KB6).
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from typing import Iterable

try:  # sqlite-vec is optional for pure schema tests
    import sqlite_vec
except Exception:  # pragma: no cover - exercised only on a minimal host
    sqlite_vec = None


SCHEMA_VERSION = "2"
VECTOR_DIM = 768

BASE_TOOL_COLUMNS = (
    ("rowid", "INTEGER PRIMARY KEY"),
    ("name", "TEXT UNIQUE NOT NULL"),
    ("category", "TEXT NOT NULL DEFAULT ''"),
    ("description", "TEXT NOT NULL DEFAULT ''"),
    ("signature", "TEXT NOT NULL DEFAULT ''"),
    ("example", "TEXT NOT NULL DEFAULT ''"),
    ("params_json", "TEXT NOT NULL DEFAULT '{}'"),
)

EXTENDED_TOOL_COLUMNS = (
    ("flags_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("options_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("source", "TEXT NOT NULL DEFAULT ''"),
    ("grass_version", "TEXT NOT NULL DEFAULT ''"),
    ("content_hash", "TEXT NOT NULL DEFAULT ''"),
    ("source_mismatches_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("xml_validated", "INTEGER NOT NULL DEFAULT 0"),
)

REQUIRED_META_KEYS = (
    "schema_version",
    "grass_version",
    "gisbase",
    "source",
    "built_at",
    "tool_count",
    "section_count",
    "content_hash",
)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate: ceil(chars / 3.5) plus a 10% margin."""
    if not text:
        return 0
    return int(math.ceil((len(text) / 3.5) * 1.1))


def canonical_content(record: dict) -> str:
    """Stable JSON used for the record's content hash."""
    fields = {
        "name": record.get("name", ""),
        "category": record.get("category", ""),
        "description": record.get("description", ""),
        "signature": record.get("signature", ""),
        "example": record.get("example", ""),
        "params": record.get("params", {}),
        "flags": record.get("flags", []),
        "options": record.get("options", {}),
        "sections": record.get("sections", {}),
        "source_mismatches": record.get("source_mismatches", []),
        "xml_validated": bool(record.get("xml_validated", False)),
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def content_hash(record: dict) -> str:
    import hashlib

    return hashlib.sha256(canonical_content(record).encode("utf-8")).hexdigest()


def open_database(path: str, load_vectors: bool = True) -> sqlite3.Connection:
    """Open (creating when needed) a KB connection with sqlite-vec loaded."""
    conn = sqlite3.connect(path)
    if load_vectors and sqlite_vec is not None:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _tool_columns(conn: sqlite3.Connection) -> set[str]:
    if not _table_exists(conn, "tools"):
        return set()
    return {row[1] for row in conn.execute("PRAGMA table_info(tools)").fetchall()}


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create or additively migrate every Feature 004 object."""
    columns = _tool_columns(conn)
    if not columns:
        definitions = ", ".join(f"{name} {kind}" for name, kind in BASE_TOOL_COLUMNS)
        conn.execute(f"CREATE TABLE IF NOT EXISTS tools ({definitions})")
        columns = {name for name, _ in BASE_TOOL_COLUMNS}
    for name, kind in EXTENDED_TOOL_COLUMNS:
        if name not in columns:
            conn.execute(f"ALTER TABLE tools ADD COLUMN {name} {kind}")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_flags ("
        "tool_name TEXT NOT NULL,"
        "flag TEXT NOT NULL,"
        "description TEXT NOT NULL DEFAULT '',"
        "generic INTEGER NOT NULL DEFAULT 0,"
        "gui_section TEXT NOT NULL DEFAULT '',"
        "PRIMARY KEY (tool_name, flag)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_options ("
        "tool_name TEXT NOT NULL,"
        "parameter TEXT NOT NULL,"
        "value TEXT NOT NULL,"
        "description TEXT NOT NULL DEFAULT '',"
        "ordinal INTEGER NOT NULL DEFAULT 0,"
        "PRIMARY KEY (tool_name, parameter, value)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_sections ("
        "tool_name TEXT NOT NULL,"
        "section TEXT NOT NULL,"
        "ordinal INTEGER NOT NULL DEFAULT 0,"
        "text TEXT NOT NULL DEFAULT '',"
        "token_estimate INTEGER NOT NULL DEFAULT 0,"
        "content_hash TEXT NOT NULL DEFAULT '',"
        "PRIMARY KEY (tool_name, section, ordinal)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS db_meta ("
        "key TEXT PRIMARY KEY,"
        "value TEXT NOT NULL DEFAULT ''"
        ")"
    )
    conn.commit()


def ensure_vector_table(conn: sqlite3.Connection, dim: int = VECTOR_DIM) -> None:
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS tools_vec USING vec0("
        f"rowid INTEGER PRIMARY KEY, embedding FLOAT[{dim}] distance_metric=cosine)"
    )


def _normalise_flags(flags: Iterable) -> list[dict]:
    normalised = []
    for flag in flags or []:
        if hasattr(flag, "__dict__") and not isinstance(flag, dict):
            payload = {
                "flag": getattr(flag, "flag", ""),
                "description": getattr(flag, "description", ""),
                "generic": bool(getattr(flag, "generic", False)),
                "gui_section": getattr(flag, "gui_section", ""),
            }
        else:
            payload = dict(flag)
        normalised.append(
            {
                "flag": str(payload.get("flag", "")),
                "description": str(payload.get("description", "")),
                "generic": bool(payload.get("generic", False)),
                "gui_section": str(payload.get("gui_section", "")),
            }
        )
    return normalised


def _normalise_options(options: dict) -> dict[str, list[dict]]:
    normalised: dict[str, list[dict]] = {}
    for parameter, entries in (options or {}).items():
        values = []
        for index, entry in enumerate(entries or []):
            if hasattr(entry, "__dict__") and not isinstance(entry, dict):
                payload = {
                    "value": getattr(entry, "value", ""),
                    "description": getattr(entry, "description", ""),
                    "ordinal": getattr(entry, "ordinal", index),
                }
            else:
                payload = dict(entry)
            values.append(
                {
                    "parameter": parameter,
                    "value": str(payload.get("value", "")),
                    "description": str(payload.get("description", "")),
                    "ordinal": int(payload.get("ordinal", index) or index),
                }
            )
        if values:
            normalised[parameter] = values
    return normalised


def _normalise_sections(sections: dict) -> dict[str, list[dict]]:
    normalised: dict[str, list[dict]] = {}
    for section, entries in (sections or {}).items():
        if isinstance(entries, str):
            entries = [{"text": entries}]
        values = []
        for index, entry in enumerate(entries or []):
            if hasattr(entry, "__dict__") and not isinstance(entry, dict):
                payload = {
                    "text": getattr(entry, "text", ""),
                    "ordinal": getattr(entry, "ordinal", index),
                    "token_estimate": getattr(entry, "token_estimate", 0),
                    "content_hash": getattr(entry, "content_hash", ""),
                }
            else:
                payload = dict(entry)
            text = str(payload.get("text", ""))
            values.append(
                {
                    "section": section,
                    "ordinal": int(payload.get("ordinal", index) or index),
                    "text": text,
                    "token_estimate": int(
                        payload.get("token_estimate", 0) or estimate_tokens(text)
                    ),
                    "content_hash": str(
                        payload.get("content_hash", "") or _text_hash(text)
                    ),
                }
            )
        if values:
            normalised[section] = values
    return normalised


def _text_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upsert_tool(conn: sqlite3.Connection, record: dict, embedding=None) -> int:
    """Insert or replace one complete manual record idempotently.

    Returns the tool's rowid. Content hashes are derived from the canonical
    record, so re-running the builder on unchanged sources does not change
    stored hashes or create duplicate rows.
    """
    ensure_schema(conn)
    flags = _normalise_flags(record.get("flags", []))
    options = _normalise_options(record.get("options", {}))
    sections = _normalise_sections(record.get("sections", {}))
    source_mismatches = list(record.get("source_mismatches", []) or [])

    payload = {
        "name": record["name"],
        "category": record.get("category", record["name"].split(".")[0]),
        "description": record.get("description", ""),
        "signature": record.get("signature", ""),
        "example": record.get("example", ""),
        "params": record.get("params", {}),
        "flags": flags,
        "options": options,
        "sections": sections,
        "source_mismatches": source_mismatches,
        "xml_validated": bool(record.get("xml_validated", False)),
    }
    digest = record.get("content_hash") or content_hash(payload)

    existing = conn.execute(
        "SELECT rowid FROM tools WHERE name = ?", (payload["name"],)
    ).fetchone()
    values = (
        payload["category"],
        payload["description"],
        payload["signature"],
        payload["example"],
        json.dumps(payload["params"], sort_keys=True),
        json.dumps(flags, sort_keys=True),
        json.dumps(options, sort_keys=True, default=str),
        record.get("source", ""),
        record.get("grass_version", ""),
        digest,
        json.dumps(source_mismatches, sort_keys=True, default=str),
        1 if payload["xml_validated"] else 0,
    )
    if existing is None:
        cursor = conn.execute(
            "INSERT INTO tools (name, category, description, signature, example, "
            "params_json, flags_json, options_json, source, grass_version, "
            "content_hash, source_mismatches_json, xml_validated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (payload["name"], *values),
        )
        rowid = int(cursor.lastrowid)
    else:
        rowid = int(existing[0])
        conn.execute(
            "UPDATE tools SET category = ?, description = ?, signature = ?, "
            "example = ?, params_json = ?, flags_json = ?, options_json = ?, "
            "source = ?, grass_version = ?, content_hash = ?, "
            "source_mismatches_json = ?, xml_validated = ? WHERE name = ?",
            (*values, payload["name"]),
        )

    for table in ("tool_flags", "tool_options", "tool_sections"):
        conn.execute(f"DELETE FROM {table} WHERE tool_name = ?", (payload["name"],))

    for flag in flags:
        conn.execute(
            "INSERT OR REPLACE INTO tool_flags "
            "(tool_name, flag, description, generic, gui_section) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                payload["name"],
                flag["flag"],
                flag["description"],
                1 if flag["generic"] else 0,
                flag["gui_section"],
            ),
        )
    for parameter, entries in options.items():
        for entry in entries:
            conn.execute(
                "INSERT OR REPLACE INTO tool_options "
                "(tool_name, parameter, value, description, ordinal) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    payload["name"],
                    parameter,
                    entry["value"],
                    entry["description"],
                    entry["ordinal"],
                ),
            )
    for section, entries in sections.items():
        for entry in entries:
            conn.execute(
                "INSERT OR REPLACE INTO tool_sections "
                "(tool_name, section, ordinal, text, token_estimate, content_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    payload["name"],
                    section,
                    entry["ordinal"],
                    entry["text"],
                    entry["token_estimate"],
                    entry["content_hash"],
                ),
            )

    if embedding is not None:
        ensure_vector_table(conn, len(embedding))
        serialized = (
            sqlite_vec.serialize_float32(embedding) if sqlite_vec is not None else embedding
        )
        conn.execute("DELETE FROM tools_vec WHERE rowid = ?", (rowid,))
        conn.execute(
            "INSERT INTO tools_vec (rowid, embedding) VALUES (?, ?)",
            (rowid, serialized),
        )
    return rowid


def write_db_meta(conn: sqlite3.Connection, meta: dict) -> None:
    ensure_schema(conn)
    for key, value in meta.items():
        if isinstance(value, (dict, list)):
            stored = json.dumps(value, sort_keys=True)
        else:
            stored = str(value)
        conn.execute(
            "INSERT INTO db_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, stored),
        )


def read_db_meta(conn: sqlite3.Connection) -> dict:
    if not _table_exists(conn, "db_meta"):
        return {}
    return {
        row[0]: row[1]
        for row in conn.execute("SELECT key, value FROM db_meta").fetchall()
    }


def meta_complete(meta: dict) -> bool:
    return all(str(meta.get(key, "")) != "" for key in REQUIRED_META_KEYS)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
