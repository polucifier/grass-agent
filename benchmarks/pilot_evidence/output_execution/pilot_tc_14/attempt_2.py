from grass.tools import Tools
tools = Tools()

# Clean the road network vector by removing duplicate line segments and snapping nodes with a 1-meter threshold
tools.v_clean(input="roadsmajor", output="roadsmajor_clean", tool="rmv")
tools.v_clean(input="roadsmajor_clean", output="pilot_roads_clean", tool="snap", threshold=1)
