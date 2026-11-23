"""Reference implementation for pilot_tc_12 (human-reviewed golden script)."""

from grass.tools import Tools

tools = Tools()
tools.r_relief(
    input="elevation", output="pilot_relief", azimuth=315, altitude=45
)
