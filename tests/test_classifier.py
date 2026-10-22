"""Failure classification against real GRASS 8.5 output (tasks T034, T035).

Every string in the catalogue below was captured by running GRASS 8.5.0 on the
Gate 2 planning host. They are not invented -- see research.md R7.

Two properties are load-bearing and easy to regress:

  * No pattern may anchor on `ERROR:`. `grass.tools` raises `ToolError`, and for
    single-line stderr its message has that prefix *stripped* (research R8).
  * `unknown_method` is tested before the content modes, because the mandated
    precedence would otherwise file every hallucinated method into the
    catch-all (decision D8).
"""

import pytest

from grass_agent.classifier import (
    FailureMode,
    classify,
    combine,
    error_excerpt,
    extract_failing_tool,
    match_mode,
    normalise,
    strip_noise,
)

# --------------------------------------------------------------------------
# Catalogue captured from live GRASS 8.5 (research R7)
# --------------------------------------------------------------------------

MISSING_INPUT_CASES = [
    "ERROR: Raster map <nonexistent> not found",
    "ERROR: Vector map <nonexistent> not found",
    "ERROR: Vector map <nosuchmap> not found in current mapset",
    "ERROR: Vector map <nosuchmap> not found in the current mapset. Unable to\n"
    "       modify vector maps from different mapsets.",
    "ERROR: Database connection not defined for layer <1>",
    "ERROR: Database connection not defined for layer <99>",
    # A missing table is a WARNING with rc=1, not an ERROR.
    "WARNING: Table <nope> not found in database "
    "<$GISDBASE/x/PERMANENT/sqlite/sqlite.db> using driver\n         <sqlite>",
    "ERROR: Mapset <nosuchmapset> does not exist",
    "ERROR: Space time raster dataset <nope@PERMANENT> not found",
    # r.out.gdal words this as "map or group".
    "Raster map or group <nosuchraster> not found",
    "ERROR: Unable to read input from <no_such_file.txt>",
    "ERROR: Unable to open input file <no_such_file.txt>: No such file or\n"
    "       directory",
    "ERROR: Unable to open datasource <no_such.tif>",
    # GDAL: bare `ERROR <n>:`, no "ERROR: " prefix, no "not found" wording.
    "ERROR 4: /tmp/opencode/scratch/no.tif: No such file or directory",
    # r.mapcalc's only reliable missing-input signal.
    "Invalid map <missingmap>\nParse error\nERROR: parse error",
    # Single-line ToolError: the `ERROR: ` prefix is already stripped here.
    "grass.tools.session_tools.ToolError: Raster map <nope> not found\n"
    "Run `r.slope.aspect elevation=nope slope=s aspect=a` ended with an error "
    "(return code 1)",
]

SCHEMA_MISUSE_CASES = [
    "ERROR: Required parameter <map> not set:\n\t(Name of raster map)",
    "ERROR: Required parameter <input> not set:\n\t(Name of input vector map)",
    "ERROR: Required parameter <column> not set",
    "ERROR: At least one of the following options is required: <slope>, "
    "<aspect>, <pcurvature> and <dxy>",
    "ERROR: r.info: Sorry, <bogus> is not a valid parameter",
    "ERROR: r.mapcalc: Sorry, <output> is not a valid parameter",
    "ERROR: Sorry<extra1> is not a valid option",
    # Harvested live: an abbreviated option name that collides with several.
    "ERROR: r.stats: Sorry, <n=> is ambiguous",
    "ERROR: Option <null_value=> matches",
    # Harvested live: bad *values* for otherwise-valid options.
    "Category value in 'nosuch' not valid\n"
    "Run `v.extract input=streams output=o2 cat=nosuch` ended with an error (return code 1)",
    "The column option requires a valid layer.\n"
    "Run `v.buffer input=streams output=o3 column=nocol` ended with an error (return code 1)",
    "ERROR: No 'from' features selected. Please check options 'from_layer',\n"
    "       'from_where', 'from_cats'.",
    "ERROR: Value <bogus> out of range for parameter <type>\n"
    "\tLegal range: raster,raster_3d,vector,label,region,group,all",
    "ERROR: option <slope>: <dem> exists. To overwrite, use the --overwrite flag",
    "ERROR: Select a buffer distance/minordistance/angle or column, but not\n"
    "       both.",
    "syntax error\nParse error\nERROR: parse error",
]

UNKNOWN_METHOD_CASES = [
    "AttributeError: Tool v_update_column (v.update.column) not found "
    "(but found v_db_addcolumn)",
    "AttributeError: Tool r_mapcalc_ (r.mapcalc.) not found "
    "(but found r3_mapcalc, r_mapcalc)",
    "AttributeError: Tool or attribute foobar_baz_qux (foobar.baz.qux) not found "
    "(check session setup and documentation for tool and attribute names)",
    "AttributeError: Tool or attribute r_slope (r.slope) not found "
    "(check session setup and documentation for tool and attribute names)",
    "AttributeError: module grass.tools has no attribute Nope",
    "OSError: Cannot find the executable r.nonexistenttool",
    "TypeError: ToolFunctionResolver.get_function.<locals>.wrapper() takes "
    "0 positional arguments but 1 was given",
]

GENERAL_CASES = [
    "ModuleNotFoundError: No module named 'nonexistent_module_xyz'",
    "SyntaxError: invalid syntax",
    "grass.tools.session_tools.ToolError: Output of r.info cannot be parsed "
    "as JSON. Did you use format=\"json\"?",
    "ValueError: No text output for r.info to be parsed as JSON",
    "ZeroDivisionError: division by zero",
    "KeyError: 'elevation'",
]

ALL_CATALOGUE = (
    [(text, FailureMode.MISSING_INPUT) for text in MISSING_INPUT_CASES]
    + [(text, FailureMode.SCHEMA_MISUSE) for text in SCHEMA_MISUSE_CASES]
    + [(text, FailureMode.UNKNOWN_METHOD) for text in UNKNOWN_METHOD_CASES]
    + [(text, FailureMode.GENERAL_EXCEPTION) for text in GENERAL_CASES]
)


# --------------------------------------------------------------------------
# Catalogue mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stderr_text,expected", ALL_CATALOGUE, ids=lambda v: str(v)[:40])
def test_real_grass_strings_classify_correctly(stderr_text, expected):
    assert classify("", stderr_text) is expected


@pytest.mark.parametrize("stderr_text", [t for t, _ in ALL_CATALOGUE])
def test_classification_is_idempotent(stderr_text):
    """Same input, same mode, every time (SC-005a)."""
    modes = {classify("", stderr_text) for _ in range(5)}
    assert len(modes) == 1


def test_every_mode_is_reachable():
    """All four modes must be reachable, else the enum is misdesigned."""
    seen = {classify("", text) for text, _ in ALL_CATALOGUE}
    assert seen == set(FailureMode)


# --------------------------------------------------------------------------
# The two design constraints that are easy to regress
# --------------------------------------------------------------------------


def test_toolerror_with_stripped_prefix_still_matches():
    """A single-line ToolError has no `ERROR: ` anchor available.

    This is the case an anchored pattern would miss entirely (decision D7).
    """
    text = (
        "grass.tools.session_tools.ToolError: Raster map <nope> not found\n"
        "Run `r.slope.aspect elevation=nope slope=s` ended with an error "
        "(return code 1)"
    )
    assert classify("", text) is FailureMode.MISSING_INPUT


def test_hallucinated_method_does_not_fall_into_catch_all():
    """The mandated precedence, applied literally, would misfile this.

    AttributeError matches no content pattern, so testing unknown_method last
    would dump the entire category into general_exception (decision D8).
    """
    text = (
        "AttributeError: Tool v_update_column (v.update.column) not found "
        "(but found v_db_addcolumn)"
    )
    assert classify("", text) is FailureMode.UNKNOWN_METHOD


def test_missing_input_beats_schema_misuse_when_both_present():
    """The overlap the precedence order exists to resolve."""
    text = (
        "ERROR: Raster map <nonexistent> not found\n"
        "ERROR: r.info: Sorry, <bogus> is not a valid parameter\n"
    )
    assert classify("", text) is FailureMode.MISSING_INPUT


def test_schema_misuse_beats_general_when_parse_error_present():
    text = "syntax error\nParse error\nERROR: parse error"
    assert classify("", text) is FailureMode.SCHEMA_MISUSE


def test_invalid_map_beats_parse_error():
    """`Invalid map <x>` must be evaluated before `Parse error`.

    Both a bad expression and a missing map end in identical `Parse error`
    lines; only the `Invalid map` line distinguishes them.
    """
    assert classify("", "Invalid map <missingmap>\nParse error") is FailureMode.MISSING_INPUT
    assert classify("", "syntax error\nParse error") is FailureMode.SCHEMA_MISUSE


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def test_continuation_indent_is_normalised():
    """GRASS wraps at ~72 chars with a 7-space indent, splitting phrases."""
    wrapped = (
        "ERROR: Vector map <nosuchmap> not found in the current mapset. Unable to\n"
        "       modify vector maps from different mapsets."
    )
    assert "\n       " not in normalise(wrapped)
    assert classify("", wrapped) is FailureMode.MISSING_INPUT


def test_german_locale_still_classifies():
    """The host locale must not change the classification.

    A German locale translates GRASS error text, which would silently empty
    the missing_input bucket. The executor pins LC_ALL precisely because of
    this (decision D9).
    """
    german = (
        "grass.tools.session_tools.ToolError: Rasterkarte <nope> konnte nicht "
        "gefunden werden.\n"
        "Run `r.slope.aspect elevation=nope` ended with an error (return code 1)"
    )
    # Whatever the mode, it must be deterministic and never raise.
    assert classify("", german) is classify("", german)


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


def test_error_excerpt_is_verbatim_substring():
    """Contract invariant I8: the excerpt must be a real substring."""
    stderr_text = (
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1\n'
        "grass.tools.session_tools.ToolError: Raster map <nope> not found\n"
    )
    excerpt = error_excerpt("", stderr_text)
    assert excerpt in stderr_text
    assert "Raster map" in excerpt


def test_error_excerpt_prefers_error_lines():
    stderr_text = "progress...\nERROR: Required parameter <map> not set\nmore progress\n"
    assert "Required parameter" in error_excerpt("", stderr_text)


def test_error_excerpt_skips_traceback_frame_lines():
    """A naive "contains 'error'" search picks GRASS's own source.

    `return gs.handle_errors(` contains "error" but carries no diagnostic
    value; handing it to the repair prompt actively misleads the model.
    """
    stderr_text = (
        "Traceback (most recent call last):\n"
        '  File "support.py", line 591, in call_cmd\n'
        "    return gs.handle_errors(\n"
        "           ~~~~~~~~~~~~~~~~\n"
        "grass.tools.session_tools.ToolError: Raster map <nope> not found\n"
    )
    excerpt = error_excerpt("", stderr_text)
    assert excerpt in stderr_text
    assert "Raster map" in excerpt
    assert "handle_errors" not in excerpt


def test_error_excerpt_unwraps_multiline_toolerror():
    """A multi-line ToolError hides the cause under its own wrapper line."""
    stderr_text = (
        "grass.tools.session_tools.ToolError: Run `v.net.distance input=streams` "
        "ended with an error (return code 1):\n"
        "ERROR: No 'from' features selected. Please check options 'from_layer',\n"
        "       'from_where', 'from_cats'.\n"
    )
    excerpt = error_excerpt("", stderr_text)
    assert excerpt.startswith("ERROR:")
    assert "features selected" in excerpt


def test_grass_session_chatter_is_stripped():
    """GRASS session chatter must never be mistaken for a diagnosis.

    Observed on the Gate 2 host: ~/.grass8/bashrc names a shell GRASS does not
    support, and GRASS warns about it on stderr before the script runs. Left
    in, that WARNING wins every "first WARNING" race in error_excerpt and the
    repair model is handed a line about the host's bashrc.
    """
    chatter = "WARNING: Unsupported shell <fish>: /home/rhea/.grass8/bashrc\n"
    stderr_text = chatter + "ERROR: Raster map <nope> not found\n"
    assert "fish" not in error_excerpt("", stderr_text)
    assert error_excerpt("", stderr_text).startswith("ERROR:")
    assert "fish" not in strip_noise(chatter)


def test_strip_noise_keeps_real_diagnostics():
    stderr_text = (
        "WARNING: Unsupported shell <fish>: /home/rhea/.grass8/bashrc\n"
        "0%\n50%\n100%\n"
        "ERROR: Raster map <nope> not found\n"
    )
    stripped = strip_noise(stderr_text)
    assert "fish" not in stripped
    assert "100%" not in stripped
    assert "Raster map <nope> not found" in stripped


def test_excerpt_when_nothing_but_chatter_survives():
    """Better to say nothing was captured than to quote host noise."""
    chatter = "WARNING: Unsupported shell <fish>: /home/rhea/.grass8/bashrc\n"
    assert error_excerpt("", chatter) == chatter.strip()
    assert error_excerpt("", "") == "(no output captured)"


def test_classifier_covers_harvested_live_failures():
    """Failures observed running real modules, not just the written catalogue."""
    observed = [
        ("Run `r.watershed elevation=x` ended with an error (return code 1):\n"
         "SECTION 1a (of 4): Initiating Memory.\n"
         "ERROR: Raster map <nosuchraster> not found", FailureMode.MISSING_INPUT),
        ("Category value in 'nosuch' not valid", FailureMode.SCHEMA_MISUSE),
        ("The column option requires a valid layer.", FailureMode.SCHEMA_MISUSE),
        ("ERROR: No 'from' features selected. Please check options 'from_layer'.",
         FailureMode.SCHEMA_MISUSE),
        ("ERROR: r.stats: Sorry, <n=> is ambiguous", FailureMode.SCHEMA_MISUSE),
        ("ERROR: Option <null_value=> matches", FailureMode.SCHEMA_MISUSE),
        ("Raster map or group <nosuchraster> not found", FailureMode.MISSING_INPUT),
    ]
    for text, expected in observed:
        assert classify("", text) is expected, text.splitlines()[0]


@pytest.mark.parametrize(
    "stderr_text,expected_tool",
    [
        (
            "AttributeError: Tool v_update_column (v.update.column) not found "
            "(but found v_db_addcolumn)",
            "v.update.column",
        ),
        (
            "AttributeError: Tool or attribute foobar_baz_qux (foobar.baz.qux) "
            "not found (check session setup)",
            "foobar.baz.qux",
        ),
        (
            "grass.tools.session_tools.ToolError: Raster map <nope> not found\n"
            "Run `r.slope.aspect elevation=nope` ended with an error (return code 1)",
            "r.slope.aspect",
        ),
        ("ModuleNotFoundError: No module named 'xyz'", None),
    ],
)
def test_failing_tool_extraction(stderr_text, expected_tool):
    assert extract_failing_tool("", stderr_text) == expected_tool


def test_match_mode_returns_none_for_unrecognised():
    assert match_mode(combine("", "something entirely unexpected")) is None


def test_unrecognised_failure_never_dropped():
    """An unmatched failure becomes general_exception, never None (FR-008)."""
    assert classify("", "totally novel failure mode 12345") is FailureMode.GENERAL_EXCEPTION