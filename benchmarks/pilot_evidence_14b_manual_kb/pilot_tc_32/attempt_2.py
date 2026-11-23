from grass.tools import Tools
tools = Tools()

# Calculate slope from the elevation raster
tools.r_slope_aspect(elevation="elevation", slope="pilot_steep_slope")

# Reclassify slopes greater than 15 degrees into steep areas
rules = """
0:15:1
15.01:*:2
"""
tools.r_reclass(input="pilot_steep_slope", output="pilot_steep_reclass", rules=rules)

# Convert the steep areas to vector polygons
tools.r_to_vect(input="pilot_steep_reclass", output="pilot_steep", type="area", column="value")
