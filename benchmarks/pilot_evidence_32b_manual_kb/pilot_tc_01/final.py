from grass.tools import Tools
tools = Tools()
tools.v_buffer(input="streams", type="line", distance=200, output="pilot_streams_buffer")
