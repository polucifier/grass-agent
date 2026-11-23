from grass.tools import Tools
tools = Tools()
tools.v_clean(input="roadsmajor", output="roadsmajor_clean1", tool="rmdupl")
tools.v_clean(input="roadsmajor_clean1", output="pilot_roads_clean", tool="snap", threshold=1)
