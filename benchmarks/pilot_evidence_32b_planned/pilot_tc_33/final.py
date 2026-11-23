from grass.tools import Tools
tools = Tools()
tools.v_to_rast(input="hospitals", type="point", use="value", value=1, output="pilot_hospitals_raster")
tools.r_grow_distance(input="pilot_hospitals_raster", distance="pilot_distance", metric="euclidean")
