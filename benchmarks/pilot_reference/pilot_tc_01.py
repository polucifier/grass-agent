"""Reference implementation for pilot_tc_01 (human-reviewed golden script)."""

from grass.tools import Tools

tools = Tools()
tools.v_buffer(input="streams", output="pilot_streams_buffer", distance=200)
