"""Reference implementation for pilot_tc_08 (human-reviewed golden script).

`-b` is mandatory: without it r.viewshed writes elevation differences, not the
binary 0/1 visibility raster the prompt requires.
"""

from grass.tools import Tools

tools = Tools()
tools.r_viewshed(
    input="elevation",
    output="pilot_viewshed",
    coordinates=[635000, 216500],
    flags="b",
)
