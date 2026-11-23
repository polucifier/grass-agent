from grass.tools import Tools
tools = Tools()
tools.r_slope_aspect(elevation="elevation", slope="pilot_steep_slope", zscale=1.0, min_slope=0.0, nprocs=0, memory=300)
tools.r_reclass(input="pilot_steep_slope", output="steep_areas", rules="- | 15:9999 = 1\n* = 0")
tools.r_to_vect(input="steep_areas", output="pilot_steep", type="area")
