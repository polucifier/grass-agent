from grass.tools import Tools
tools = Tools()
tools.v_clean(input="roadsmajor", output="pilot_roads_clean", tool="rmdupl")
tools.v_clean(input="pilot_roads_clean", output="pilot_roads_clean", tool="snap", threshold=1)
