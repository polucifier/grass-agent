from grass.tools import Tools
tools = Tools()

# Convert hospitals vector points into a raster map
tools.v_to_rast(input="hospitals", output="pilot_hospitals_raster", use="attr")

# Calculate the minimum Euclidean distance from each cell to the nearest hospital
tools.r_grow_distance(input="pilot_hospitals_raster", distance="pilot_distance", metric="euclidean")
