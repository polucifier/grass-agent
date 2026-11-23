from grass.tools import Tools
tools = Tools()
tools.v_to_rast(input="hospitals", type="point", output="pilot_hospitals_raster", use="cat", value=1)
tools.r_grow_distance(input="pilot_hospitals_raster", distance="pilot_distance", metric="euclidean")
