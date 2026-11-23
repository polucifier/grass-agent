"""Markdown/HTML/XML parsing and merge for the local knowledge base.

Markdown is authoritative for API parameter names, Python types, and defaults;
XML is authoritative for flags, requiredness, ``multiple``, and finite
``<values>`` sets. Disagreements are never dropped: they are returned in the
record's ``source_mismatches`` list and summarised by the builder.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .kb_schema import estimate_tokens

SYNTHETIC_FLAGS = ("flags", "overwrite", "verbose", "quiet", "superquiet")
GENERIC_FLAG_NAMES = ("overwrite", "verbose", "quiet", "superquiet", "help", "ui")

_RANGE_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*-\s*-?\d+(?:\.\d+)?\s*$")
_PATH_RE = re.compile(r"(^/|\\|\.(?:shp|txt|csv|tif|tiff|gpkg|geojson|json)\b)")
_EXPRESSION_RE = re.compile(r"[=+\-*/()<>]|^[A-Za-z_]\w*\s+thru\s+")
_SIGNATURE_RE = re.compile(r"\*grass\.tools\.Tools\.([A-Za-z0-9_]+)\*\((.*?)\)", re.DOTALL)
_PY_PARAM_RE = re.compile(
    r"\*\*([A-Za-z_][A-Za-z0-9_]*)\*\*\s*:\s*([^\n,]+?)\s*,\s*\*(required|optional)\*"
)
_CLI_PARAM_RE = re.compile(r"^\s*\*\*([A-Za-z_][A-Za-z0-9_]*)\*\*=\*([^*]+)\*(.*)$")
_CLI_FLAG_RE = re.compile(r"^\s*(?:\*\*)?-([A-Za-z])(?:\*\*)?\s*$")
_CLI_GENERIC_RE = re.compile(r"^\s*(?:\*\*)?--([A-Za-z][A-Za-z0-9_]*)(?:\*\*)?\s*$")
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_TAB_RE = re.compile(r'^===\s+"([^"]+)"\s*$', re.MULTILINE)


@dataclass
class ParsedMarkdown:
    name: str = ""
    description: str = ""
    signature: str = ""
    params: dict = field(default_factory=dict)
    flags: list[dict] = field(default_factory=list)
    markdown_options: dict[str, list[dict]] = field(default_factory=dict)
    sections: dict[str, list[dict]] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)
    front_matter: dict = field(default_factory=dict)

    @property
    def has_manual(self) -> bool:
        return bool(self.name)


@dataclass
class ParsedXml:
    name: str = ""
    description: str = ""
    params: dict = field(default_factory=dict)
    flags: list[dict] = field(default_factory=list)
    options: dict[str, list[dict]] = field(default_factory=dict)


def _clean(text: str) -> str:
    """Collapse Markdown emphasis and whitespace into canonical plain text."""
    text = text.replace("\u00a0", " ")
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&amp;", "&")
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def split_args(body: str) -> list[str]:
    """Split a Python signature body on top-level commas."""
    parts: list[str] = []
    current = ""
    depth = 0
    quote: str | None = None
    for char in body + ",":
        if quote:
            current += char
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
            current += char
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    return [part for part in parts if part]


def _signature_from_block(block: str) -> str:
    match = _SIGNATURE_RE.search(block)
    if not match:
        return ""
    method, body = match.group(1), match.group(2)
    arguments = _clean(body).replace("\n", " ")
    return f"grass.tools.Tools.{method}({arguments})"


def _params_from_signature(signature: str) -> dict:
    if "(" not in signature or ")" not in signature:
        return {}
    method = signature.split("(", 1)[0]
    body = signature.split("(", 1)[1].rsplit(")", 1)[0]
    params: dict = {}
    for part in split_args(body):
        part = part.strip().rstrip(",")
        if not part or part == "self":
            continue
        if "=" in part:
            name, default = part.split("=", 1)
            name = name.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            params[name] = {
                "type": "",
                "required": False,
                "default": _clean(default).strip("\"'"),
            }
        else:
            name = part.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                continue
            params[name] = {"type": "", "required": True}
    # Keep the method name discoverable without storing it in params.
    params.pop("_method", None)
    params["__method__"] = method  # internal; removed before persistence
    return params


def _parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("'\"")
    return meta, parts[2]


def _tab_blocks(body: str) -> dict[str, str]:
    matches = list(_TAB_RE.finditer(body))
    if not matches:
        return {}
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        blocks[match.group(1)] = body[start:end]
    return blocks


def _canonical_tab(blocks: dict[str, str]) -> str:
    for label in ("Python (grass.tools)", "Python (grass.script)"):
        if label in blocks:
            return blocks[label]
    return next(iter(blocks.values()), "")


def _parse_cli_flags(block: str) -> list[dict]:
    flags: list[dict] = []
    lines = block.splitlines()
    for index, line in enumerate(lines):
        match = _CLI_FLAG_RE.match(line)
        generic = None
        if match:
            flag = match.group(1)
        else:
            generic = _CLI_GENERIC_RE.match(line)
            if not generic:
                continue
            flag = generic.group(1)
        description = ""
        for following in lines[index + 1 :]:
            stripped = following.strip()
            if not stripped or stripped.startswith("**"):
                break
            description = _clean(stripped)
            break
        flags.append(
            {
                "flag": flag,
                "description": description,
                "generic": bool(generic) or flag in GENERIC_FLAG_NAMES,
                "gui_section": "",
            }
        )
    return flags


def _parse_cli_params(block: str) -> dict[str, dict]:
    """Extract requiredness, defaults, descriptions, and finite allowed values."""
    result: dict[str, dict] = {}
    lines = block.splitlines()
    current: str | None = None
    for line in lines:
        match = _CLI_PARAM_RE.match(line)
        if match:
            current = match.group(1)
            entry = {
                "type": _clean(match.group(2)),
                "required": "[required]" in match.group(3),
                "description": "",
            }
            result[current] = entry
            continue
        if current is None:
            continue
        stripped = _clean(line)
        if not stripped:
            continue
        if stripped.startswith("Default:"):
            result[current]["default"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Allowed values:"):
            raw = stripped.split(":", 1)[1].strip()
            values = [value.strip() for value in raw.split(",") if value.strip()]
            if values and is_closed_enum_values(current, values):
                result[current]["options"] = values
        elif stripped.startswith("**"):
            continue
        elif not result[current]["description"]:
            result[current]["description"] = stripped
    return result


def parse_markdown(path: str | Path) -> ParsedMarkdown:
    """Parse one local Markdown manual page."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    front_matter, body = _parse_front_matter(text)
    name = front_matter.get("name", "")
    if not name:
        heading = re.search(r"^#\s+(\S+)\s*$", body, re.MULTILINE)
        name = heading.group(1) if heading else Path(path).stem

    parsed = ParsedMarkdown(name=name, front_matter=front_matter)
    parsed.description = front_matter.get("description", "")

    signature = _signature_from_block(body)
    parsed.signature = signature
    raw_params = _params_from_signature(signature)
    method = raw_params.pop("__method__", "")
    parsed.params = raw_params

    # Python parameter table gives types and requiredness. Restrict the tab
    # scan to the Parameters section so the Python tab is selected rather than
    # whichever tab happens to appear first in the document.
    parameter_body = ""
    for match in _SECTION_RE.finditer(body):
        if match.group(1).strip().upper() == "PARAMETERS":
            start = match.end()
            following = _SECTION_RE.search(body, start)
            parameter_body = body[start : following.start() if following else len(body)]
            break
    parameter_tabs = _tab_blocks(parameter_body)
    python_block = (
        parameter_tabs.get("Python (grass.tools)", "")
        or _canonical_tab(parameter_tabs)
        or parameter_body
    )
    for match in _PY_PARAM_RE.finditer(python_block):
        param = match.group(1)
        if param in parsed.params:
            parsed.params[param]["type"] = _clean(match.group(2))
            parsed.params[param]["required"] = match.group(3) == "required"

    # Command-line tab carries flags and finite allowed values.
    cli_block = parameter_tabs.get("Command line", "")
    parsed.flags = _parse_cli_flags(cli_block)
    cli_params = _parse_cli_params(cli_block)
    for param, entry in cli_params.items():
        if param in parsed.params:
            if not parsed.params[param].get("type"):
                parsed.params[param]["type"] = entry.get("type", "")
            if "default" not in parsed.params[param] or entry.get("default"):
                parsed.params[param].setdefault("default", entry.get("default"))
            if entry.get("description") and not parsed.params[param].get("description"):
                parsed.params[param]["description"] = entry["description"]
        if entry.get("options"):
            parsed.markdown_options[param] = [
                {
                    "parameter": param,
                    "value": value,
                    "description": "",
                    "ordinal": ordinal,
                }
                for ordinal, value in enumerate(entry["options"])
            ]

    if not parsed.description:
        paragraph = re.search(r"^#\s+\S+\s*\n+(.+?)\n\s*\n", body, re.MULTILINE | re.DOTALL)
        if paragraph:
            parsed.description = _clean(paragraph.group(1).splitlines()[0])

    # Canonical sections: one per heading, tabs collapsed.
    matches = list(_SECTION_RE.finditer(body))
    for index, match in enumerate(matches):
        section = match.group(1).strip().upper()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section_body = body[start:end]
        tabs = _tab_blocks(section_body)
        content = _canonical_tab(tabs) if tabs else section_body
        content = _dedent_markdown(content)
        if not content.strip():
            continue
        parsed.sections.setdefault(section, []).append(
            {
                "section": section,
                "ordinal": 0,
                "text": content,
                "token_estimate": estimate_tokens(content),
            }
        )

    if "EXAMPLES" in parsed.sections:
        for entry in parsed.sections["EXAMPLES"]:
            for block in re.findall(r"```(?:python|sh)?\s*\n(.*?)```", entry["text"], re.DOTALL):
                parsed.examples.append(block.strip())
        if not parsed.examples:
            parsed.examples = [entry["text"] for entry in parsed.sections["EXAMPLES"]][:2]

    return parsed


def _dedent_markdown(text: str) -> str:
    lines = text.splitlines()
    indents = [
        len(line) - len(line.lstrip())
        for line in lines
        if line.strip() and not line.strip().startswith("===")
    ]
    trim = min(indents) if indents else 0
    cleaned = [line[trim:] if len(line) >= trim else line for line in lines]
    return "\n".join(cleaned).strip()


def is_closed_enum_values(parameter: str, values: list[str]) -> bool:
    """True only for a genuinely finite allowed-value set.

    Ranges, free text, map names, file paths, and expressions are explicitly
    excluded (FR-007, data-model ClosedEnumOption rules).
    """
    if not values:
        return False
    for value in values:
        candidate = value.strip()
        if not candidate:
            return False
        if _RANGE_RE.match(candidate):
            return False
        if _PATH_RE.search(candidate):
            return False
        if _EXPRESSION_RE.search(candidate):
            return False
    if parameter in {"input", "output", "error", "map", "raster", "vector"}:
        return False
    return True


def _element_text(element) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def parse_xml(xml_text: str) -> ParsedXml:
    """Parse a GRASS ``--interface-description`` XML document."""
    root = ET.fromstring(xml_text)
    parsed = ParsedXml()
    parsed.name = root.attrib.get("name", "")
    parsed.description = _element_text(root.find("description"))

    for parameter in root.findall("parameter"):
        name = parameter.attrib.get("name", "")
        if not name:
            continue
        entry = {
            "name": name,
            "type": parameter.attrib.get("type", ""),
            "required": parameter.attrib.get("required", "no") == "yes",
            "multiple": parameter.attrib.get("multiple", "no") == "yes",
            "default": _element_text(parameter.find("default")),
            "description": _element_text(parameter.find("description")),
        }
        parsed.params[name] = entry

        values_element = parameter.find("values")
        if values_element is None:
            continue
        value_elements = values_element.findall("value")
        range_elements = values_element.findall("range")
        choices: list[dict] = []
        for ordinal, value in enumerate(value_elements):
            value_name = _element_text(value.find("name"))
            if not value_name:
                continue
            choices.append(
                {
                    "parameter": name,
                    "value": value_name,
                    "description": _element_text(value.find("description")),
                    "ordinal": ordinal,
                }
            )
        # A range, or any mixture, is not a closed enum.
        if choices and not range_elements:
            if all(is_closed_enum_values(name, [choice["value"]]) for choice in choices):
                parsed.options[name] = choices

    for flag in root.findall("flag"):
        flag_name = flag.attrib.get("name", "")
        if not flag_name:
            continue
        parsed.flags.append(
            {
                "flag": flag_name,
                "description": _element_text(flag.find("description")),
                "generic": flag_name in GENERIC_FLAG_NAMES,
                "gui_section": _element_text(flag.find("guisection")),
            }
        )
    return parsed


def parse_html(path: str | Path) -> ParsedMarkdown:
    """Fallback parser for local ``docs/html`` pages."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(Path(path).read_text(encoding="utf-8", errors="replace"), "html.parser")
    heading = soup.find("h1")
    name = heading.get_text(strip=True) if heading else Path(path).stem
    parsed = ParsedMarkdown(name=name)
    if heading:
        paragraph = heading.find_next("p")
        if paragraph:
            parsed.description = _clean(paragraph.get_text(" "))

    section_names = {
        "description": "DESCRIPTION",
        "notes": "NOTES",
        "examples": "EXAMPLES",
        "synopsis": "SYNOPSIS",
        "see also": "SEE ALSO",
    }
    for h2 in soup.find_all("h2"):
        title = h2.get_text(strip=True).lower()
        section = section_names.get(title, title.upper())
        chunks = []
        for sibling in h2.find_next_siblings():
            if sibling.name in ("h2", "h1"):
                break
            chunks.append(sibling.get_text("\n", strip=True))
        text = "\n".join(chunk for chunk in chunks if chunk)
        if text:
            parsed.sections.setdefault(section, []).append(
                {
                    "section": section,
                    "ordinal": 0,
                    "text": text,
                    "token_estimate": estimate_tokens(text),
                }
            )
    if "EXAMPLES" in parsed.sections:
        parsed.examples = [entry["text"] for entry in parsed.sections["EXAMPLES"]][:2]
    return parsed


def _synthesize_params(params: dict) -> None:
    """Ensure the five synthetic flag kwargs exist on every record (KB3)."""
    for name in SYNTHETIC_FLAGS:
        entry = params.setdefault(name, {})
        entry.setdefault("required", False)
        entry.setdefault("default", None)
        if name == "flags":
            entry.setdefault("type", "str | list[str]")
        else:
            entry.setdefault("type", "bool")


def _synthesize_generic_flags(flags: list[dict]) -> list[dict]:
    existing = {flag["flag"] for flag in flags}
    for name in GENERIC_FLAG_NAMES:
        if name == "ui":
            continue
        if name not in existing:
            flags.append(
                {
                    "flag": name,
                    "description": f"Synthetic generic flag keyword ({name})",
                    "generic": True,
                    "gui_section": "",
                }
            )
    return flags


def merge_records(
    name: str,
    markdown: ParsedMarkdown | None,
    xml: ParsedXml | None,
    grass_version: str = "",
    gisbase: str = "",
) -> dict:
    """Merge Markdown and XML into one complete manual record."""
    markdown = markdown or ParsedMarkdown(name=name)
    mismatches: list[dict] = []

    params: dict = {
        param: dict(entry)
        for param, entry in markdown.params.items()
        if param not in SYNTHETIC_FLAGS
    }

    # XML enriches matching names; unknown names are recorded, never injected
    # into the authoritative signature.
    if xml is not None:
        for param, entry in xml.params.items():
            if param not in params:
                mismatches.append(
                    {
                        "parameter": param,
                        "markdown_value": "",
                        "xml_value": param,
                        "kind": "missing_in_markdown",
                    }
                )
                continue
            target = params[param]
            if not target.get("type"):
                target["type"] = entry.get("type", "")
            if entry.get("required"):
                target["required"] = True
            if entry.get("default") and not target.get("default"):
                target["default"] = entry["default"]
            if entry.get("description"):
                target.setdefault("description", entry["description"])
            target["multiple"] = bool(entry.get("multiple", False))
        for param in params:
            if param not in xml.params and param not in SYNTHETIC_FLAGS:
                mismatches.append(
                    {
                        "parameter": param,
                        "markdown_value": param,
                        "xml_value": "",
                        "kind": "missing_in_xml",
                    }
                )

    # Closed enums: XML first, then Markdown's finite "Allowed values".
    options: dict[str, list[dict]] = {}
    if xml is not None:
        for param, choices in xml.options.items():
            if param in params:
                options[param] = choices
                md_values = [
                    entry["value"]
                    for entry in markdown.markdown_options.get(param, [])
                ]
                if md_values and md_values != [choice["value"] for choice in choices]:
                    mismatches.append(
                        {
                            "parameter": param,
                            "markdown_value": ",".join(md_values),
                            "xml_value": ",".join(choice["value"] for choice in choices),
                            "kind": "enum_mismatch",
                        }
                    )
    for param, choices in markdown.markdown_options.items():
        if param in params and param not in options:
            options[param] = choices

    _synthesize_params(params)

    flags = list(xml.flags) if xml is not None else list(markdown.flags)
    if xml is not None:
        # Markdown may expose a flag XML omitted; record the disagreement and
        # keep XML authoritative for the flag set.
        xml_flags = {flag["flag"] for flag in xml.flags}
        for flag in markdown.flags:
            if not flag["generic"] and flag["flag"] not in xml_flags:
                mismatches.append(
                    {
                        "parameter": f"-{flag['flag']}",
                        "markdown_value": flag["flag"],
                        "xml_value": "",
                        "kind": "missing_in_xml",
                    }
                )
    flags = _synthesize_generic_flags(flags)

    sections = markdown.sections or {}
    example = ""
    if markdown.examples:
        example = markdown.examples[0].strip()
    elif "EXAMPLES" in sections and sections["EXAMPLES"]:
        example = sections["EXAMPLES"][0]["text"].strip()

    description = (xml.description if xml is not None and xml.description else "") or markdown.description
    signature = markdown.signature
    if not signature and xml is not None and params:
        method = name.replace(".", "_")
        arguments = ", ".join(
            param if entry.get("required") else f"{param}=None"
            for param, entry in params.items()
            if param not in SYNTHETIC_FLAGS
        )
        signature = f"grass.tools.Tools.{method}({arguments})"

    record = {
        "name": name,
        "category": name.split(".")[0],
        "description": description,
        "signature": signature,
        "example": example,
        "params": params,
        "flags": flags,
        "options": options,
        "sections": sections,
        "source": "",
        "grass_version": grass_version,
        "source_mismatches": mismatches,
        "xml_validated": xml is not None,
        "gisbase": gisbase,
    }
    return record


def parse_module(
    name: str,
    markdown_path: str = "",
    html_path: str = "",
    xml_text: str = "",
    grass_version: str = "",
    gisbase: str = "",
) -> dict:
    """Parse one module from whichever local sources exist and merge them."""
    markdown = None
    if markdown_path:
        markdown = parse_markdown(markdown_path)
    elif html_path:
        markdown = parse_html(html_path)
    else:
        markdown = ParsedMarkdown(name=name)
    xml = parse_xml(xml_text) if xml_text else None
    record = merge_records(name, markdown, xml, grass_version=grass_version, gisbase=gisbase)
    sources = []
    if markdown_path:
        sources.append(f"markdown:{markdown_path}")
    if html_path:
        sources.append(f"html:{html_path}")
    if xml_text:
        sources.append("xml:interface-description")
    record["source"] = ";".join(sources)
    return record
