"""Reference implementation for pilot_tc_09 (human-reviewed golden script)."""

from grass.tools import Tools

tools = Tools()
tools.r_mapcalc(expression="pilot_elevation_double = elevation * 2")
