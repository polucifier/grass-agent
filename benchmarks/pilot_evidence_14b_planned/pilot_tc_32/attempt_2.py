from grass.tools import Tools
tools = Tools()

# Calculate slope from the elevation raster
tools.r_slope_aspect(elevation="elevation", slope="pilot_steep_slope")

# Reclassify slopes greater than 15 degrees into steep areas
rules = """
<15:1
15:*
"""
tools.r_reclass(input="pilot_steep_slope", output="steep_areas", rules=rules)

# Convert the steep areas to vector polygons
tools.r_to_vect(input="steep_areas", output="pilot_steep", type="area")

# Print the results
print("Slope raster map: pilot_steep_slope")
print("Steep areas vector map: pilot_steep")
