"""Reference implementation for pilot_tc_33 (human-reviewed golden script)."""

from grass.tools import Tools

tools = Tools()
tools.v_to_rast(
    input="hospitals",
    output="pilot_hospitals_raster",
    type="point",
    use="val",
    value=1,
)
tools.r_grow_distance(
    input="pilot_hospitals_raster", distance="pilot_distance"
)
