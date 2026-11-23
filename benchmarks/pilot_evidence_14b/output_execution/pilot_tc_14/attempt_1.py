from grass.tools import Tools
tools = Tools()

# Clean the road network by removing duplicate line segments and snapping nodes
tools.v_clean(input="roadsmajor", output="pilot_roads_clean", tool="break")
tools.v_edit(map="pilot_roads_clean", tool="snap", threshold="1.0")
