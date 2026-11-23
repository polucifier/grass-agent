from grass.tools import Tools
tools = Tools()
tools.v_buffer(input="streams", output="pilot_streams_buffer_100m", distance=100, type="line")
tools.v_to_rast(input="pilot_streams_buffer_100m", output="pilot_streams_buffer_raster", use="value", value=1)
