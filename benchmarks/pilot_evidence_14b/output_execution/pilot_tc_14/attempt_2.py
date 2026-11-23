from grass.tools import Tools
tools = Tools()

# Clean the road network by removing duplicate line segments and snapping nodes
tools.v_edit(map="roadsmajor", tool="break")
tools.v_edit(map="roadsmajor", tool="snap", threshold="1.0")
tools.v_out_ogr(input="roadsmajor", output="pilot_roads_clean", format="ESRI_Shapefile")
