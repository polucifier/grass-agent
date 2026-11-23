from grass.tools import Tools
tools = Tools()
tools.v_clean(input="roadsmajor", output="pilot_roads_clean", tool="rm_duplicates")
tools.v_edit(map="pilot_roads_clean", tool="snap", threshold="1")
