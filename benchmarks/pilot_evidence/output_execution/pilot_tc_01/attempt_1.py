from grass.tools import Tools
tools = Tools()

# Create a 200-meter buffer around the stream network lines
tools.v_buffer(input="streams", output="pilot_streams_buffer", distance=200)
