from grass.tools import Tools
tools = Tools()

# Step 1: Create a buffer around the stream network lines
tools.v_buffer(input="streams", output="pilot_streams_buffer", distance=200, type="line")
