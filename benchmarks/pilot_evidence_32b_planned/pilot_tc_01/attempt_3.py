from grass.tools import Tools
tools = Tools()
tools.v_buffer(input="streams", output="pilot_streams_buffer", type="line", distance=200, flags="t", tolerance=0.02)
