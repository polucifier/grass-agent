"""Failure classification for Gate 2 (FR-008, FR-008a).

Every failed attempt lands in exactly one of four modes, resolved
deterministically. The classification order is:

    1. unknown_method   -- disjoint from the others, tested first
    2. missing_input    \
    3. schema_misuse     >-- mandated precedence over competing content modes
    4. general_exception /  (catch-all: timeouts, crashes, anything unrecognised)

**Why unknown_method is tested first.** The mandated precedence is
missing_input -> schema_misuse -> unknown_method -> general. Applied as a
literal match order it would file every hallucinated `tools.v_update_column`
into the catch-all, because an `AttributeError` line matches none of the
content patterns. Testing it first is collision-free: research verified that
`ToolError` message text never contains the phrase `Tool <x> ... not found`,
while leaving the mode last would misfile the entire category (decision D8).

**No pattern anchors on `ERROR:`.** `grass.tools` wraps module failures in
`ToolError`, and for single-line stderr its message has the `ERROR: ` prefix
stripped. An anchored pattern would miss every single-line case. Some failures
also surface as `WARNING:` with rc=1 (a missing table via db.select), so the
anchor is not merely inconvenient but wrong (decision D7, research R8).
"""

from __future__ import annotations

import re
from enum import Enum


class FailureMode(str, Enum):
    """The four mutually exclusive failure categories (FR-008)."""

    MISSING_INPUT = "missing_input"
    SCHEMA_MISUSE = "schema_misuse"
    UNKNOWN_METHOD = "unknown_method"
    GENERAL_EXCEPTION = "general_exception"


# --------------------------------------------------------------------------
# Text normalisation
# --------------------------------------------------------------------------

# GRASS hard-wraps messages at ~72 characters with a 7-space continuation
# indent, splitting them mid-sentence. Un-indenting continuation lines before
# matching is what lets a pattern like `not found in the current mapset` match
# a message that was wrapped in the middle of that phrase.
_CONTINUATION_INDENT = re.compile(r"(?m)^[ \t]+")


def normalise(text: str) -> str:
    """Collapse GRASS's continuation indentation so patterns see one line."""
    return _CONTINUATION_INDENT.sub(" ", text)


def combine(stdout: str, stderr: str) -> str:
    """Join captured streams into the single text the classifier scans."""
    return normalise(f"{stdout or ''}\n{stderr or ''}")


# --------------------------------------------------------------------------
# unknown_method -- tested first (decision D8)
# --------------------------------------------------------------------------

# Real GRASS 8.5 wording. `'Tools' object has no attribute 'x'` does NOT occur
# on this install: Tools.__getattr__ intercepts and raises a plain
# AttributeError from ToolFunctionResolver.get_tool_name (research R7).
UNKNOWN_METHOD_PATTERNS = (
    re.compile(r"AttributeError:\s*Tool\s+[^\n]*?\s+not\s+found"),
    re.compile(r"AttributeError:\s*Tool\s+or\s+attribute\s+[^\n]*?\s+not\s+found"),
    re.compile(r"AttributeError:\s*module\s+grass\.tools\s+has\s+no\s+attribute"),
    re.compile(r"(?:OSError|FileNotFoundError):\s*Cannot\s+find\s+the\s+executable\s+\S+"),
    # Only positional args to a tool method raise TypeError. A wrong *keyword*
    # is forwarded by make_command and becomes schema_misuse, not a TypeError.
    re.compile(
        r"TypeError:\s*ToolFunctionResolver\.get_function\.<locals>\.wrapper\(\)"
        r"\s+takes\s+\d+\s+positional\s+arguments?"
    ),
)


# --------------------------------------------------------------------------
# missing_input
# --------------------------------------------------------------------------

MISSING_INPUT_PATTERNS = (
    # `Raster map <x> not found`, `Vector map <x> not found`, plus the
    # "not found in current mapset" / "not found in the current mapset" variants.
    # `Raster map or group <x> not found` (r.out.gdal) needs the alternation.
    re.compile(r"\b(?:Raster|Vector)\s+(?:map\s+or\s+group\s+|map\s+)?<[^>]+>\s+not\s+(?:be\s+)?found\b"),
    re.compile(r"\bSpace\s+time\s+raster\s+dataset\s+<[^>]+>\s+not\s+found"),
    re.compile(r"\bMapset\s+<[^>]+>\s+does\s+not\s+exist"),
    re.compile(r"\bDatabase\s+connection\s+not\s+defined\s+for\s+layer\s+<[^>]+>"),
    # A missing table is reported as WARNING: with rc=1, not ERROR:.
    re.compile(r"\bTable\s+<[^>]+>\s+not\s+found\s+in\s+database\b"),
    # r.mapcalc's only reliable missing-input signal: both a bad expression and
    # a missing map produce identical trailing "Parse error" lines.
    re.compile(r"\bInvalid\s+map\s+<[^>]+>"),
    re.compile(r"\bUnable\s+to\s+read\s+input\s+from\s+<[^>]+>"),
    re.compile(r"\bUnable\s+to\s+open\s+input\s+file\s+<[^>]+>"),
    re.compile(r"\bUnable\s+to\s+open\s+datasource\s+<[^>]+>"),
    # GDAL reports this with a bare `ERROR <n>:` -- no "ERROR: " prefix and no
    # "not found" wording, so it needs its own alternative.
    re.compile(r"^ERROR\s+\d+:\s+\S*:\s+No\s+such\s+file\s+or\s+directory", re.MULTILINE),
)


# --------------------------------------------------------------------------
# schema_misuse
# --------------------------------------------------------------------------

SCHEMA_MISUSE_PATTERNS = (
    # Two variants: with a colon + tab-indented description, and bare.
    re.compile(r"\bRequired\s+parameter\s+<[^>]+>\s+not\s+set"),
    re.compile(r"\bAt\s+least\s+one\s+of\s+the\s+following\s+options\s+is\s+required"),
    re.compile(r"\bSorry,\s*<[^>]+>\s+is\s+not\s+a\s+valid\s+parameter"),
    re.compile(r"\bSorry\s*<[^>]+>\s+is\s+not\s+a\s+valid\s+option"),
    # Abbreviated option names collide with several real options at once.
    re.compile(r"\bSorry,\s*<[^>]+>\s+is\s+ambiguous\b"),
    re.compile(r"\bOption\s+<[^>]+>\s+matches\b"),
    re.compile(r"\bValue\s+<[^>]+>\s+out\s+of\s+range\s+for\s+parameter\s+<[^>]+>"),
    re.compile(r"\boption\s+<[^>]+>:\s*<[^>]+>\s+exists\.\s*To\s+overwrite"),
    re.compile(r"^\s*Parse\s+error\s*$", re.MULTILINE),
    re.compile(r"\bSelect\s+a\s+buffer\s+distance/minordistance/angle\s+or\s+column,\s+but\s+not\s+both"),
    # Harvested from live GRASS 8.5 (see tests/test_classifier.py catalogue):
    # bad *values* for otherwise-valid options.
    re.compile(r"\bCategory\s+value\s+in\s+'[^']+'\s+not\s+valid\b"),
    re.compile(r"\bThe\s+column\s+option\s+requires\s+a\s+valid\s+layer\b"),
    re.compile(r"\bNo\s+'[\w ]+'\s+features\s+selected\b"),
)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

_MODE_PATTERNS: tuple[tuple[FailureMode, tuple[re.Pattern, ...]], ...] = (
    (FailureMode.UNKNOWN_METHOD, UNKNOWN_METHOD_PATTERNS),
    (FailureMode.MISSING_INPUT, MISSING_INPUT_PATTERNS),
    (FailureMode.SCHEMA_MISUSE, SCHEMA_MISUSE_PATTERNS),
)


def match_mode(text: str) -> FailureMode | None:
    """Return the mode `text` matches, or None if it matches nothing.

    Deterministic and idempotent: identical text always yields an identical
    result, because the order below is fixed and the patterns are anchored
    (SC-005a).
    """
    for mode, patterns in _MODE_PATTERNS:
        for pattern in patterns:
            if pattern.search(text):
                return mode
    return None


def classify(stdout: str, stderr: str) -> FailureMode:
    """Classify a failed attempt into exactly one FailureMode (FR-008).

    An unrecognised failure is assigned GENERAL_EXCEPTION rather than dropped,
    so 100% of failed attempts land in one of the four modes (SC-005).
    """
    text = strip_noise(combine(stdout, stderr))
    return match_mode(text) or FailureMode.GENERAL_EXCEPTION


# GRASS session-start chatter that is unrelated to the script's failure.
# Observed on this host: the user's ~/.grass8/bashrc names a shell GRASS does
# not support, and GRASS warns about it at startup -- on stderr, before the
# script runs. Treating it as the failure hands the repair model a line about
# the host's bashrc instead of the actual error.
_NOISE_PATTERNS = (
    re.compile(r"^WARNING:\s*Unsupported shell\b"),
    re.compile(r"^WARNING:\s*Default locale settings are missing\b"),
    re.compile(r"^\s*\d+(\.\d+)?%\s*$"),
    re.compile(r"^(Cleaning up temporary files|Building topology|Importing|Solving|Snapping)\b"),
    re.compile(r"^\s*$"),
)


def strip_noise(text: str) -> str:
    """Remove GRASS session chatter, leaving lines that can carry a diagnosis."""
    kept = [line for line in text.splitlines() if not any(p.match(line) for p in _NOISE_PATTERNS)]
    return "\n".join(kept)


# The final line of a Python traceback: `pkg.mod.SomeError: message`.
_EXCEPTION_LINE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning|Exit))\s*:\s*(.*)$")
# A traceback frame's source line, e.g. `    return gs.handle_errors(`.
# These contain "error" as a substring but carry no diagnostic value.
_TRACEBACK_SOURCE = re.compile(r"^\s{4,}\S")


def error_excerpt(stdout: str, stderr: str, limit: int = 400) -> str:
    """Extract the single most diagnostic line from captured output.

    Fed verbatim into the repair prompt (FR-010), so choosing badly actively
    harms healing: a naive "first line containing 'error'" search picks up a
    traceback *frame* such as `return gs.handle_errors(` and hands the model a
    line from GRASS's own source instead of the actual failure.

    Session chatter (bashrc warnings, progress percentages) is stripped first:
    it lands on stderr before the script has done anything, so it would otherwise
    win every "first WARNING" race and hide the real failure.

    Preference order:
      1. the trailing exception line -- what Python prints last
      2. an `ERROR:` line
      3. a `WARNING:` line (a missing table surfaces this way, rc=1)
      4. the first line containing a GRASS map reference
      5. the first non-blank line of output

    The result is always a verbatim substring of the captured text
    (contract invariant I8).
    """
    lines = [line.strip() for line in strip_noise(stderr or "").splitlines()]
    lines = [line for line in lines if line]

    # 1. the trailing exception line
    for line in reversed(lines):
        if _TRACEBACK_SOURCE.match(line):
            continue
        if _EXCEPTION_LINE.match(line):
            # A multi-line ToolError wraps the real diagnostic: its own message
            # ends with "ended with an error (return code 1):" and the actual
            # GRASS error follows underneath. The wrapper names the command
            # (useful) but the inner ERROR names the cause (decisive), so
            # surface the cause and keep the command in the repair prompt via
            # the full traceback.
            if line.rstrip().endswith(":"):
                for inner in lines:
                    if inner.startswith(("ERROR:", "ERROR ")):
                        return inner[:limit]
            return line[:limit]

    # 2/3. module-reported errors and warnings
    for prefix in ("ERROR:", "ERROR ", "WARNING:"):
        for line in lines:
            if line.startswith(prefix):
                return line[:limit]

    # 4. a line naming a map, which is what most GRASS failures are about
    for line in lines:
        if re.search(r"<\w+>", line):
            return line[:limit]

    # 5. anything non-blank, preferring a line that is not session chatter
    for stream in (strip_noise(stderr or ""), strip_noise(stdout or "")):
        for line in stream.splitlines():
            stripped = line.strip()
            if stripped and not _TRACEBACK_SOURCE.match(stripped):
                return stripped[:limit]

    # Nothing survived stripping -- returning raw output beats returning nothing,
    # but say so plainly rather than dressing host chatter up as a diagnosis.
    raw = (stderr or "").strip() or (stdout or "").strip()
    return (raw[:limit] if raw else "(no output captured)")


# --------------------------------------------------------------------------
# Failing-tool extraction
# --------------------------------------------------------------------------

# `Tool v_update_column (v.update.column) not found`  ->  v.update.column
_TOOL_NAME_FROM_ATTRIBUTE_ERROR = re.compile(
    r"Tool\s+(?:or\s+attribute\s+)?([A-Za-z0-9_.]+)\s+\(([^)]*)\)\s+not\s+found"
)
# `Run `r.slope.aspect elevation=x` ended with an error`  ->  r.slope.aspect
_TOOL_NAME_FROM_TOOLERROR = re.compile(r"Run\s+`([A-Za-z0-9_.]+)")
# `ERROR: Unable to open datasource <x>` has no tool; a bare tool invocation
# like `r.info map=...` in the traceback is the last resort.
_TOOL_NAME_FROM_COMMAND = re.compile(r"\b((?:r|v|g|db|i|t|d|m|p|q)\.[a-z0-9_.]+)\b")


def extract_failing_tool(stdout: str, stderr: str) -> str | None:
    """Return the GRASS tool name implicated in a failure, or None.

    Drives the targeted RAG re-query (FR-011). Returns None when no tool can be
    identified -- callers must then fall back to querying with the error
    excerpt itself, which is required behaviour rather than an error path.
    """
    text = combine(stdout, stderr)

    match = _TOOL_NAME_FROM_ATTRIBUTE_ERROR.search(text)
    if match:
        dotted = match.group(2).strip()
        # Python 3.13 renders `Did you mean: ...?` in the traceback but not in
        # str(e); the parenthetical is authoritative when it holds a real name.
        if dotted and "nonexistent" not in dotted and ".." not in dotted:
            return dotted
        return match.group(1).replace("_", ".")

    match = _TOOL_NAME_FROM_TOOLERROR.search(text)
    if match:
        return match.group(1)

    match = _TOOL_NAME_FROM_COMMAND.search(text)
    if match:
        return match.group(1)
    return None