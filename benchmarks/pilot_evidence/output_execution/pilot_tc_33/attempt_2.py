from grass.tools import Tools
tools = Tools()

# Convert the hospitals vector points into a raster map
hospitals_raster = "pilot_hospitals_raster"
tools.v_to_rast(input="hospitals", output=hospitals_raster, use="attr")

# Calculate the minimum Euclidean distance from each cell to the nearest hospital
pilot_distance = "pilot_distance"
tools.r_grow_distance(input=hospitals_raster, distance=pilot_distance, metric="euclidean")
