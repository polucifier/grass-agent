"""Reference implementation for pilot_tc_32 (human-reviewed golden script).

Slopes strictly greater than 15 degrees become steep; everything else is NULL
so r.to.vect emits only the steep polygons.
"""

from grass.tools import Tools

tools = Tools()
tools.r_slope_aspect(elevation="elevation", slope="pilot_steep_slope")

with open("pilot_reclass_rules.txt", "w", encoding="utf-8") as handle:
    handle.write("0 thru 15 = NULL\n")
    handle.write("* = 1\n")

tools.r_reclass(
    input="pilot_steep_slope",
    output="pilot_steep_binary",
    rules="pilot_reclass_rules.txt",
)
tools.r_to_vect(input="pilot_steep_binary", output="pilot_steep", type="area")
