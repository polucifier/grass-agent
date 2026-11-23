#!/usr/bin/env python3
"""Build the local GRASS knowledge base without any network access.

Sources, in precedence order, are the installed ``$GISBASE`` Markdown manuals,
the local XML interface descriptions, and local HTML manuals. Nothing here
imports ``requests`` or any other network client.

    python scripts/build_knowledge_base.py \
      --gisbase "$(grass --config path)" \
      --db data/grass_knowledge.db --source local --rebuild
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grass_agent import kb_schema  # noqa: E402
from grass_agent.kb_parse import parse_module  # noqa: E402
from grass_agent.kb_source import (  # noqa: E402
    XmlUnavailable,
    enumerate_modules,
    grass_version,
    load_xml_descriptions,
    read_manifest,
    resolve_gisbase,
)

DEFAULT_DB = REPO_ROOT / "data" / "grass_knowledge.db"
DEFAULT_REPORT = REPO_ROOT / "data" / "kb_build_report.json"
MANIFEST = REPO_ROOT / "benchmarks" / "kb_required_modules.txt"
EMBED_MODEL = "nomic-embed-text"
MAX_COMMIT_BYTES = 50 * 1024 * 1024

EXIT_OK = 0
EXIT_ARG = 2
EXIT_MISSING = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the local GRASS 8.5 knowledge base (offline only)."
    )
    parser.add_argument("--gisbase", default=None, help="$GISBASE or grass --config path")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite destination")
    parser.add_argument("--source", default="local", choices=("local",), help="Source policy")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild all records")
    parser.add_argument("--strict", action="store_true", help="Fail on any missing manual or XML")
    parser.add_argument("--partial", action="store_true", help="Allow optional/add-on skips")
    parser.add_argument("--dataset-project", default=None, help="Project for the XML session")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Build report path")
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST),
        help="Authoritative benchmark module manifest",
    )
    return parser


def _embed_text(record: dict) -> str:
    return " ".join(
        [
            record.get("name", ""),
            record.get("description", ""),
            record.get("signature", ""),
            record.get("example", ""),
            " ".join(
                f"{param}:{info.get('type', '')}"
                for param, info in (record.get("params") or {}).items()
            ),
        ]
    )[:3000]


def _embed(client, text: str) -> list[float]:
    response = client.embeddings(model=EMBED_MODEL, prompt=text, options={"num_ctx": 8192})
    return response["embedding"]


def build(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.strict and args.partial:
        print("Error: --strict and --partial are mutually exclusive", file=sys.stderr)
        return EXIT_ARG

    try:
        gisbase = resolve_gisbase(args.gisbase)
    except XmlUnavailable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_MISSING
    version = grass_version()

    try:
        manifest = read_manifest(args.manifest)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_MISSING
    manifest_set = set(manifest)

    inventory = enumerate_modules(gisbase)
    sources = {module.name: module for module in inventory.modules}
    candidates = sorted(sources)

    xml_map: dict[str, str] = {}
    xml_error = ""
    try:
        xml_map = load_xml_descriptions(
            candidates,
            gisbase=gisbase,
            dataset_project=args.dataset_project,
        )
    except XmlUnavailable as exc:
        xml_error = str(exc)

    try:
        import ollama
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: local model client unavailable: {exc}", file=sys.stderr)
        return EXIT_MISSING

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = kb_schema.open_database(str(db_path), load_vectors=True)
    kb_schema.ensure_schema(conn)
    kb_schema.ensure_vector_table(conn)
    if args.rebuild:
        for table in ("tools", "tool_flags", "tool_options", "tool_sections", "tools_vec"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    report = {
        "gisbase": str(gisbase),
        "grass_version": version,
        "source": "local",
        "db": str(db_path),
        "manifest": str(Path(args.manifest)),
        "modules": {},
        "omissions": [],
        "missing": [],
        "json_mode": "rebuild" if args.rebuild else "update",
        "xml_session_error": xml_error,
        "counts": {},
        "source_mismatches": {},
        "hashes": {},
        "distribution": {},
    }

    failures: list[str] = []
    stored = 0
    record_hashes: list[str] = []
    section_total = 0

    for name in candidates:
        source = sources[name]
        in_manifest = name in manifest_set
        if not source.has_manual:
            message = f"{name}: no local manual record"
            report["missing"].append(message)
            if in_manifest or args.strict:
                failures.append(message)
            else:
                report["omissions"].append(message)
            continue

        xml_text = xml_map.get(name, "")
        if not xml_text:
            message = f"{name}: XML interface description unavailable"
            if in_manifest:
                failures.append(message)
                report["missing"].append(message)
                continue
            if args.strict:
                failures.append(message)
                report["missing"].append(message)
                continue
            report["omissions"].append(message)

        try:
            record = parse_module(
                name,
                markdown_path=source.markdown_path,
                html_path=source.html_path,
                xml_text=xml_text,
                grass_version=version,
                gisbase=str(gisbase),
            )
        except Exception as exc:  # noqa: BLE001 - a parse fault is a reported omission
            message = f"{name}: parse failed: {exc}"
            report["missing"].append(message)
            if in_manifest or args.strict:
                failures.append(message)
            else:
                report["omissions"].append(message)
            continue

        if not record.get("signature") and not source.markdown_path:
            message = f"{name}: no grass.tools signature and no Markdown source"
            report["missing"].append(message)
            if in_manifest or args.strict:
                failures.append(message)
                continue
            report["omissions"].append(message)

        if record.get("source_mismatches"):
            report["source_mismatches"][name] = record["source_mismatches"]
            if args.strict and in_manifest:
                failures.append(f"{name}: Markdown/XML mismatch under --strict")

        try:
            embedding = _embed(ollama, _embed_text(record))
        except Exception as exc:  # noqa: BLE001
            message = f"{name}: embedding failed: {exc}"
            failures.append(message)
            report["missing"].append(message)
            continue

        rowid = kb_schema.upsert_tool(conn, record, embedding=embedding)
        conn.commit()
        stored += 1
        record_hashes.append(record.get("content_hash") or kb_schema.content_hash(record))
        section_total += sum(len(entries) for entries in record.get("sections", {}).values())
        report["modules"][name] = {
            "rowid": rowid,
            "source": record.get("source", ""),
            "xml_validated": bool(record.get("xml_validated")),
            "flags": len(record.get("flags", [])),
            "options": {key: len(value) for key, value in record.get("options", {}).items()},
            "sections": {key: len(value) for key, value in record.get("sections", {}).items()},
            "content_hash": record.get("content_hash") or kb_schema.content_hash(record),
        }

    import hashlib

    overall_hash = hashlib.sha256("".join(sorted(record_hashes)).encode()).hexdigest()
    tool_count = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
    meta = {
        "schema_version": kb_schema.SCHEMA_VERSION,
        "grass_version": version,
        "gisbase": str(gisbase),
        "source": "mixed" if any(m.html_path for m in inventory.modules) else "mkdocs-markdown",
        "built_at": kb_schema.now_utc(),
        "tool_count": tool_count,
        "section_count": section_total,
        "content_hash": overall_hash,
        "manifest_modules": len(manifest_set),
        "omitted_modules": len(report["omissions"]),
    }
    kb_schema.write_db_meta(conn, meta)
    conn.commit()
    conn.close()

    size = db_path.stat().st_size if db_path.is_file() else 0
    report["counts"] = {
        "inventory": len(candidates),
        "stored": stored,
        "tools": tool_count,
        "sections": section_total,
        "manifest_modules": len(manifest_set),
        "failures": len(failures),
    }
    report["hashes"] = {"content_hash": overall_hash, "records": len(record_hashes)}
    report["db_meta"] = meta
    report["distribution"] = {
        "size_bytes": size,
        "commit_db": size <= MAX_COMMIT_BYTES,
        "policy": (
            "commit data/grass_knowledge.db (<= 50 MB)"
            if size <= MAX_COMMIT_BYTES
            else "generate during setup; commit report/checksums instead (> 50 MB)"
        ),
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if xml_error and manifest_set:
        print(f"ERROR: XML session unavailable: {xml_error}", file=sys.stderr)
        return EXIT_MISSING
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        print(f"Build failed with {len(failures)} error(s); report: {report_path}", file=sys.stderr)
        return EXIT_MISSING

    print(
        f"Built {stored} module record(s) into {db_path} "
        f"({tool_count} total, {section_total} sections); report: {report_path}"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(build())
