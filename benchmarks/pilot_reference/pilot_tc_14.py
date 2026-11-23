"""Reference implementation for pilot_tc_14 (human-reviewed golden script)."""

from grass.tools import Tools

tools = Tools()
tools.v_clean(
    input="roadsmajor",
    output="pilot_roads_clean",
    tool="break,snap",
    threshold=1,
)
