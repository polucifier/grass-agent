from grass.tools import Tools
tools = Tools()

# Convert hospitals vector points to raster
tools.v_to_rast(input="hospitals", type="point", output="pilot_hospitals_raster", use="value")

# Calculate the minimum Euclidean distance from each cell to the nearest hospital
tools.r_grow_distance(input="pilot_hospitals_raster", distance="pilot_distance", metric="euclidean")
