from grass.tools import Tools
tools = Tools()
tools.v_buffer(input="streams", output="pilot_streams_buffer_100m", distances=100, units="meters")
tools.v_to_rast(input="pilot_streams_buffer_100m", output="pilot_streams_buffer_raster", use="val")
