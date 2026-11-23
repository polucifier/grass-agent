"""Reference implementation for pilot_tc_06 (human-reviewed golden script)."""

from grass.tools import Tools

tools = Tools()
tools.v_buffer(
    input="streams", output="pilot_streams_buffer_100m", distance=100
)
tools.v_to_rast(
    input="pilot_streams_buffer_100m",
    output="pilot_streams_buffer_raster",
    type="area",
    use="val",
    value=1,
)
