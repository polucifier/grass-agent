from grass.tools import Tools
tools = Tools()

# Step 1: Remove duplicate line segments
tools.v_clean(input="streets", output="streets_clean", tool="rmdupl")

# Step 2: Snap nodes with a 1-meter threshold
tools.v_clean(input="streets_clean", output="pilot_roads_clean", tool="snap", threshold=1)
