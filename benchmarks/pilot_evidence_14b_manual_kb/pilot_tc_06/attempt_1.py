from grass.tools import Tools
tools = Tools()

# Buffer the streams vector map by 100 meters
tools.v_buffer(input="streams", output="pilot_streams_buffer_100m", distances=100, units="meters")

# Convert the buffered vector areas into a raster map
tools.v_to_rast(input="pilot_streams_buffer_100m", output="pilot_streams_buffer_raster", use="cat")
