"""Pre-flight schema/version/provenance gates (T023A)."""

from __future__ import annotations

import pytest

from grass_agent import kb_schema, kb_source
from grass_agent.config import ExecutionConfig
from grass_agent.preflight import MissingDependency, check_knowledge_db


def _meta(grass_version: str) -> dict:
    return {
        "schema_version": "2",
        "grass_version": grass_version,
        "gisbase": "/usr/lib64/grass85",
        "source": "mkdocs-markdown",
        "built_at": "2026-11-19T00:00:00+00:00",
        "tool_count": "1",
        "section_count": "1",
        "content_hash": "abc",
    }


def _db_with_meta(kb_db_factory, meta):
    path, conn = kb_db_factory(
        [{"name": "r.viewshed", "description": "v", "params": {}}]
    )
    kb_schema.write_db_meta(conn, meta)
    conn.commit()
    return path, conn


def test_version_mismatch_exits_3_with_rebuild_hint(kb_db_factory):
    path, conn = _db_with_meta(kb_db_factory, _meta("8.6.0"))
    conn.close()
    config = ExecutionConfig(knowledge_db=str(path), grass_bin="grass")
    with pytest.raises(MissingDependency) as excinfo:
        check_knowledge_db(config, pipeline="manual-kb")
    message = str(excinfo.value)
    assert "knowledge base version" in message
    assert "rebuild with:" in message
    assert "build_knowledge_base.py" in message


def test_missing_provenance_exits_3(kb_db_factory):
    path, conn = _db_with_meta(kb_db_factory, _meta(kb_source.grass_version()))
    conn.execute("DELETE FROM db_meta WHERE key = 'source'")
    conn.commit()
    conn.close()
    config = ExecutionConfig(knowledge_db=str(path), grass_bin="grass")
    with pytest.raises(MissingDependency) as excinfo:
        check_knowledge_db(config, pipeline="planned")
    assert "provenance" in str(excinfo.value)
    assert "rebuild with:" in str(excinfo.value)


def test_legacy_db_is_accepted_in_legacy_mode(kb_db_factory):
    path, conn = kb_db_factory(
        [{"name": "r.viewshed", "description": "v", "params": {}}], legacy=True
    )
    conn.close()
    config = ExecutionConfig(knowledge_db=str(path), grass_bin="grass")
    assert check_knowledge_db(config, pipeline="legacy") == path


def test_gisbase_path_mismatch_alone_does_not_fail(kb_db_factory):
    meta = _meta(kb_source.grass_version())
    meta["gisbase"] = "/a/portable/prefix/grass85"
    path, conn = _db_with_meta(kb_db_factory, meta)
    conn.close()
    config = ExecutionConfig(knowledge_db=str(path), grass_bin="grass")
    assert check_knowledge_db(config, pipeline="manual-kb") == path


def test_old_schema_version_is_rejected_in_new_modes(kb_db_factory):
    meta = _meta(kb_source.grass_version())
    meta["schema_version"] = "1"
    path, conn = _db_with_meta(kb_db_factory, meta)
    conn.close()
    config = ExecutionConfig(knowledge_db=str(path), grass_bin="grass")
    with pytest.raises(MissingDependency) as excinfo:
        check_knowledge_db(config, pipeline="manual-kb")
    assert "schema_version" in str(excinfo.value)
