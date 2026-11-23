# Contract: Local Knowledge Base (`data/grass_knowledge.db`)

**Date**: 2026-11-19 | **Plan**: [../plan.md](../plan.md) | **Data model**: [../data-model.md](../data-model.md)

Normative schema and provenance contract for the offline local GRASS 8.5 knowledge base.

## 1. Source precedence

For each module:

1. `$GISBASE/docs/mkdocs/source/<module>.md` — primary: signature, Python types, defaults, allowed values, `DESCRIPTION`, `NOTES`, `EXAMPLES`.
2. `--interface-description` XML — authoritative for flags, requiredness, defaults, multiple, and closed `<values>`.
3. `$GISBASE/docs/html/<module>.html` — fallback for manual sections and flags.
4. Installed module inventory — module names only, when neither manual source is present.

`$GISBASE` is resolved from `$GISBASE` or `grass --config path`. The build is local-only.

## 2. Additive schema

### 2.1 `tools` additions

| Column | Type | Default | Meaning |
|---|---|---|---|
| `flags_json` | TEXT | `'[]'` | JSON array of `{flag, description, generic, gui_section}` |
| `options_json` | TEXT | `'{}'` | JSON object: parameter → `[{value, description, ordinal}]` |
| `source` | TEXT | `''` | Source kind and path/provenance |
| `grass_version` | TEXT | `''` | Version used to build the record |
| `content_hash` | TEXT | `''` | Hash of canonical record content |
| `source_mismatches_json` | TEXT | `'[]'` | JSON array of Markdown/XML disagreements (`parameter`, `markdown_value`, `xml_value`, `kind`) |
| `xml_validated` | INTEGER | `0` | `1` when XML enrichment was applied; `0` for Markdown-only optional/add-on records |

Existing columns (`name`, `category`, `description`, `signature`, `example`, `params_json`) remain unchanged in meaning.

### 2.2 `tool_flags`

| Column | Type | Notes |
|---|---|---|
| `tool_name` | TEXT | FK to `tools.name` |
| `flag` | TEXT | Single character or generic name |
| `description` | TEXT | English description |
| `generic` | INTEGER | 0/1 |
| `gui_section` | TEXT | Optional |

Primary key: `(tool_name, flag)`.

### 2.3 `tool_options`

| Column | Type | Notes |
|---|---|---|
| `tool_name` | TEXT | FK |
| `parameter` | TEXT | API parameter name |
| `value` | TEXT | Allowed value |
| `description` | TEXT | One-line meaning |
| `ordinal` | INTEGER | Stable source order |

Primary key: `(tool_name, parameter, value)`.

### 2.4 `tool_sections`

| Column | Type | Notes |
|---|---|---|
| `tool_name` | TEXT | FK |
| `section` | TEXT | `SYNOPSIS`, `DESCRIPTION`, `NOTES`, `EXAMPLES`, ... |
| `ordinal` | INTEGER | Stable order |
| `text` | TEXT | Canonical plain text |
| `token_estimate` | INTEGER | Conservative estimate |
| `content_hash` | TEXT | Hash |

Primary key: `(tool_name, section, ordinal)`.

### 2.5 `db_meta`

| Column | Type | Notes |
|---|---|---|
| `key` | TEXT | Primary key |
| `value` | TEXT | JSON/string value |

Required keys: `schema_version`, `grass_version`, `gisbase`, `source`, `built_at`, `tool_count`, `section_count`, `content_hash`.

`tools_vec` is preserved unchanged for tool-level embeddings.

## 3. Record completeness

A complete manual record has:

- `name`, `category`, `description`.
- A `grass.tools` signature, sourced from Markdown or synthesized from XML and marked as synthesized.
- `params_json` with type, required, default, and `options` for each API parameter.
- Synthetic API flag kwargs: `flags`, `overwrite`, `verbose`, `quiet`, `superquiet`.
- At least one of `tool_flags` or a valid empty flags set.
- At least one `tool_sections` row (`DESCRIPTION`, `NOTES`, or `EXAMPLES`) when the manual exists.
- Provenance: `source`, `grass_version`, `content_hash`, and `xml_validated`.
- Markdown/XML mismatches, when present, stored in `source_mismatches_json` and summarized in the build report.

## 4. Merge rules

- The Markdown `grass.tools` signature is authoritative for API parameter names and Python types.
- XML is authoritative for flags, requiredness, defaults, multiple, and closed values.
- If XML and Markdown disagree on a parameter name or enum set, keep the signature name, attach XML metadata where the names match, and persist the mismatch in `source_mismatches_json` and the build report.
- Deduplicate the Command-line / `grass.tools` / `grass.script` tabs; store one canonical section per heading.
- Only finite `<values>` sets become `tool_options`. Ranges, free text, map names, file paths, and expressions are not closed enums.
- Never silently drop a flag or closed enum. If parsing fails, record the module as incomplete and fail the build for manifest modules; strict mode fails for any module.

## 5. Build policy

| Situation | Partial (default) | Strict |
|---|---|---|
| Missing optional/add-on manual | Report and skip | Exit `3` |
| Missing module listed in `benchmarks/kb_required_modules.txt` | Exit `3` | Exit `3` |
| Missing XML | Manifest module: exit `3`; optional/add-on: warn, ingest from Markdown with `xml_validated=false`, skip only when no Markdown exists | Exit `3` for any module |
| Missing Markdown | Use HTML + XML; mark source | Same |
| No manual at all | Report and skip optional | Exit `3` |
| Parameter-name mismatch | Record and continue | Exit `3` |

The build is idempotent: unchanged records retain their hashes; stale records are replaced; no duplicate rows.

## 6. Query contract

- `GrassToolsRetriever.get_tool(name)` returns the existing six-field `ToolDoc` plus optional Feature 004 fields.
- `GrassToolsRetriever.get_manual(name)` returns the full `ManualRecord`, including flags, options, sections, provenance, and source mismatches.
- A missing tool returns `None`, not an exception.
- A legacy DB without new columns is readable; missing fields default to empty.
- `retrieve()` behavior is unchanged.

## 7. Version and compatibility

- New modes require `db_meta.grass_version == installed grass_version`, a compatible `schema_version`, and the required provenance keys (`source`, `built_at`, `content_hash`, `gisbase`) present.
- `gisbase` must be present but need not match the current host path; portability is allowed.
- Legacy mode accepts an old DB and performs no Feature 004 validation.
- A mismatch or missing required provenance exits `3` and prints a rebuild hint:
  `rebuild with: python scripts/build_knowledge_base.py --gisbase "$(grass --config path)" --rebuild`.
- `benchmarks/kb_required_modules.txt` is the authoritative benchmark-relevant set; the builder fails if it is missing or any listed module lacks a manual.
- Commit `data/grass_knowledge.db` only when it is at most 50 MB; otherwise generate it during setup and commit the build report and checksums. The build report records the distribution decision.

## 8. Offline guarantee

- The builder MUST NOT import `requests`, `urllib.request`, `http.client`, or any network client.
- The build reads only local paths.
- A socket-audit test raises on outbound `socket.connect` during the build and passes.

## 9. Invariants

| # | Invariant |
|---|---|
| KB1 | `tools.name` remains unique and existing rows remain readable |
| KB2 | Every new-mode record has `grass_version`, `source`, and `content_hash` |
| KB3 | `params_json` includes the five synthetic flag kwargs |
| KB4 | Closed enums contain only finite values |
| KB5 | `tool_sections` is deduplicated and deterministic |
| KB6 | A legacy DB without new columns is readable in legacy mode |
| KB7 | Strict/partial policy follows the table above |
| KB8 | Zero outbound network calls occur during build |
