"""Additive schema, provenance, idempotent rebuild, legacy readability (T009)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from grass_agent import kb_schema
from grass_agent.kb_parse import parse_module

FIXTURES = Path(__file__).parent / "fixtures" / "kb"


def _record(name: str) -> dict:
    xml = FIXTURES / "xml" / f"{name}.xml"
    return parse_module(
        name,
        markdown_path=str(FIXTURES / "markdown" / f"{name}.md"),
        xml_text=xml.read_text(encoding="utf-8") if xml.is_file() else "",
        grass_version="8.5.0",
    )


def test_schema_adds_required_tables_and_columns(tmp_path):
    conn = kb_schema.open_database(str(tmp_path / "kb.db"))
    kb_schema.ensure_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tools)")}
    assert {
        "flags_json",
        "options_json",
        "source",
        "grass_version",
        "content_hash",
        "source_mismatches_json",
        "xml_validated",
    } <= columns
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"tool_flags", "tool_options", "tool_sections", "db_meta"} <= tables
    conn.close()


def test_required_db_meta_keys(tmp_path):
    conn = kb_schema.open_database(str(tmp_path / "kb.db"))
    kb_schema.ensure_schema(conn)
    meta = {
        "schema_version": "2",
        "grass_version": "8.5.0",
        "gisbase": "/usr/lib64/grass85",
        "source": "mkdocs-markdown",
        "built_at": "2026-11-19T00:00:00+00:00",
        "tool_count": "1",
        "section_count": "3",
        "content_hash": "abc",
    }
    kb_schema.write_db_meta(conn, meta)
    assert kb_schema.read_db_meta(conn) == meta
    assert kb_schema.meta_complete(meta)
    conn.close()


def test_idempotent_rebuild_keeps_hashes_and_no_duplicates(tmp_path):
    conn = kb_schema.open_database(str(tmp_path / "kb.db"))
    kb_schema.ensure_schema(conn)
    record = _record("v.clean")
    kb_schema.upsert_tool(conn, record)
    conn.commit()
    first = conn.execute(
        "SELECT content_hash FROM tools WHERE name = 'v.clean'"
    ).fetchone()[0]
    first_sections = conn.execute("SELECT COUNT(*) FROM tool_sections").fetchone()[0]

    kb_schema.upsert_tool(conn, record)
    conn.commit()
    second = conn.execute(
        "SELECT content_hash FROM tools WHERE name = 'v.clean'"
    ).fetchone()[0]
    assert first == second
    assert conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0] == 1
    assert (
        conn.execute("SELECT COUNT(*) FROM tool_sections").fetchone()[0]
        == first_sections
    )
    conn.close()


def test_flags_and_options_are_normalised(tmp_path):
    conn = kb_schema.open_database(str(tmp_path / "kb.db"))
    kb_schema.ensure_schema(conn)
    kb_schema.upsert_tool(conn, _record("v.clean"))
    flags = {
        row[0] for row in conn.execute("SELECT flag FROM tool_flags WHERE tool_name='v.clean'")
    }
    options = {
        row[0]
        for row in conn.execute(
            "SELECT value FROM tool_options WHERE tool_name='v.clean' AND parameter='tool'"
        )
    }
    assert {"b", "c"} <= flags
    assert {"rmdupl", "snap"} <= options
    conn.close()


def test_old_six_column_db_remains_readable(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tools ("
        "rowid INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,"
        "category TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',"
        "signature TEXT NOT NULL DEFAULT '', example TEXT NOT NULL DEFAULT '',"
        "params_json TEXT NOT NULL DEFAULT '{}')"
    )
    conn.execute(
        "INSERT INTO tools (name, category, description, signature, example, params_json) "
        "VALUES ('r.viewshed', 'r', 'Viewshed', 'sig', 'ex', ?)",
        (json.dumps({"input": {"required": True}}),),
    )
    conn.commit()
    conn.close()

    from rag_retriever import GrassToolsRetriever

    retriever = GrassToolsRetriever(str(path))
    assert retriever.extended is False
    doc = retriever.get_manual("r.viewshed")
    assert doc is not None
    assert doc.params["input"]["required"] is True
    assert doc.flags == []
    assert doc.options == {}
    assert doc.xml_validated is False
    retriever.close()


def test_extended_db_returns_manual_fields(tmp_path):
    path = tmp_path / "kb.db"
    conn = kb_schema.open_database(str(path))
    kb_schema.ensure_schema(conn)
    kb_schema.upsert_tool(conn, _record("r.viewshed"))
    conn.commit()
    conn.close()

    from rag_retriever import GrassToolsRetriever

    retriever = GrassToolsRetriever(str(path))
    doc = retriever.get_manual("r.viewshed")
    assert doc is not None
    assert any(flag.flag == "b" for flag in doc.flags)
    assert doc.xml_validated is True
    assert doc.grass_version == "8.5.0"
    assert doc.section_text("NOTES")
    retriever.close()


def test_ensure_schema_is_additive_on_an_existing_legacy_db(tmp_path):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tools (rowid INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL)"
    )
    conn.execute("INSERT INTO tools (name) VALUES ('r.viewshed')")
    conn.commit()
    kb_schema.ensure_schema(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tools)")}
    assert "flags_json" in columns
    assert conn.execute("SELECT name FROM tools").fetchone()[0] == "r.viewshed"
    conn.close()
