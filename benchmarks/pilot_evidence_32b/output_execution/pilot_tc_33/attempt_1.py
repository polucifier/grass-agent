from grass.tools import Tools
tools = Tools()
tools.v_to_rast(input="hospitals", output="pilot_hospitals_raster", use="val", value=1)
tools.r_grow_distance(input="pilot_hospitals_raster", distance="pilot_distance")
