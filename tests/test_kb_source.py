"""Offline source discovery and XML-session behavior (T007/T026)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grass_agent import kb_source


def _make_gisbase(tmp_path: Path) -> Path:
    root = tmp_path / "gisbase"
    md = root / "docs" / "mkdocs" / "source"
    md.mkdir(parents=True)
    (md / "r.viewshed.md").write_text("# r.viewshed\n\nViewshed.\n", encoding="utf-8")
    (md / "v.clean.md").write_text("# v.clean\n\nClean.\n", encoding="utf-8")
    return root


def test_resolve_gisbase_from_environment(monkeypatch, tmp_path):
    root = _make_gisbase(tmp_path)
    monkeypatch.setenv("GISBASE", str(root))
    assert kb_source.resolve_gisbase() == root


def test_resolve_gisbase_from_grass_config(monkeypatch, tmp_path):
    root = _make_gisbase(tmp_path)
    monkeypatch.delenv("GISBASE", raising=False)

    class Completed:
        returncode = 0
        stdout = f"{root}\n"
        stderr = ""

    monkeypatch.setattr(kb_source.subprocess, "run", lambda *a, **k: Completed())
    assert kb_source.resolve_gisbase(grass_bin="grass") == root


def test_enumeration_is_sorted_and_hashes_content(tmp_path):
    root = _make_gisbase(tmp_path)
    inventory = kb_source.enumerate_modules(root)
    assert inventory.names() == ["r.viewshed", "v.clean"]
    assert inventory.get("r.viewshed").content_hash
    assert inventory.get("r.viewshed").source == "mkdocs-markdown"


def test_html_fallback_is_recorded(tmp_path):
    root = tmp_path / "gisbase"
    html = root / "docs" / "html"
    html.mkdir(parents=True)
    (html / "v.clean.html").write_text("<h1>v.clean</h1>", encoding="utf-8")
    inventory = kb_source.enumerate_modules(root)
    assert inventory.names() == ["v.clean"]
    assert inventory.get("v.clean").source == "html"


def test_manifest_requires_the_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        kb_source.read_manifest(tmp_path / "missing.txt")


def test_manifest_ignores_comments(tmp_path):
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("# comment\nr.viewshed\n\nv.clean\n", encoding="utf-8")
    assert kb_source.read_manifest(manifest) == ["r.viewshed", "v.clean"]


def test_xml_session_unavailable_raises(monkeypatch, tmp_path):
    root = _make_gisbase(tmp_path)

    class Failed:
        returncode = 1
        stdout = ""
        stderr = "no GRASS session"

    monkeypatch.setattr(kb_source.subprocess, "run", lambda *a, **k: Failed())
    with pytest.raises(kb_source.XmlUnavailable):
        kb_source.load_xml_descriptions(
            ["r.viewshed"], gisbase=root, grass_bin="grass", timeout=1
        )


def test_discovery_makes_no_outbound_connection(socket_guard, tmp_path):
    root = _make_gisbase(tmp_path)
    kb_source.enumerate_modules(root)
    assert socket_guard == []


def test_builder_exits_3_when_manifest_modules_lack_xml(monkeypatch, tmp_path):
    import scripts.build_knowledge_base as builder

    root = _make_gisbase(tmp_path)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("r.viewshed\n", encoding="utf-8")

    monkeypatch.setattr(builder, "resolve_gisbase", lambda *_a, **_k: root)
    monkeypatch.setattr(builder, "enumerate_modules", lambda *_a, **_k: kb_source.enumerate_modules(root))
    monkeypatch.setattr(
        builder,
        "load_xml_descriptions",
        lambda *_a, **_k: (_ for _ in ()).throw(kb_source.XmlUnavailable("no session")),
    )
    code = builder.build(
        [
            "--gisbase",
            str(root),
            "--db",
            str(tmp_path / "kb.db"),
            "--manifest",
            str(manifest),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert code == 3


def test_builder_skips_optional_modules_without_xml(monkeypatch, tmp_path):
    import scripts.build_knowledge_base as builder

    root = _make_gisbase(tmp_path)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("# no required modules\n", encoding="utf-8")

    monkeypatch.setattr(builder, "resolve_gisbase", lambda *_a, **_k: root)
    monkeypatch.setattr(builder, "enumerate_modules", lambda *_a, **_k: kb_source.enumerate_modules(root))
    monkeypatch.setattr(
        builder,
        "load_xml_descriptions",
        lambda *_a, **_k: (_ for _ in ()).throw(kb_source.XmlUnavailable("no session")),
    )
    monkeypatch.setattr(builder, "_embed", lambda *_a, **_k: [0.0] * 768)
    code = builder.build(
        [
            "--gisbase",
            str(root),
            "--db",
            str(tmp_path / "kb.db"),
            "--manifest",
            str(manifest),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    assert code == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["counts"]["stored"] == 2
    assert any("XML interface description unavailable" in item for item in report["omissions"])


@pytest.mark.slow
def test_live_manuals_expose_required_flags_and_options():
    """Live-GRASS coverage: local manuals parse without the network."""

    from grass_agent.kb_parse import parse_module

    root = kb_source.resolve_gisbase()
    inventory = kb_source.enumerate_modules(root)
    xml_map = kb_source.load_xml_descriptions(
        ["r.viewshed", "v.clean", "r.reclass"],
        gisbase=root,
        timeout=300,
    )
    viewshed = inventory.get("r.viewshed")
    assert viewshed is not None and viewshed.markdown_path
    record = parse_module(
        "r.viewshed",
        markdown_path=viewshed.markdown_path,
        xml_text=xml_map.get("r.viewshed", ""),
    )
    assert any(flag["flag"] == "b" for flag in record["flags"])

    clean = inventory.get("v.clean")
    record = parse_module(
        "v.clean",
        markdown_path=clean.markdown_path,
        xml_text=xml_map.get("v.clean", ""),
    )
    assert {"rmdupl", "snap"} <= {
        option["value"] for option in record["options"].get("tool", [])
    }

    reclass = inventory.get("r.reclass")
    record = parse_module(
        "r.reclass",
        markdown_path=reclass.markdown_path,
        xml_text=xml_map.get("r.reclass", ""),
    )
    assert "rules" in record["params"]
