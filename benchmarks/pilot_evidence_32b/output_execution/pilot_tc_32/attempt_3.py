from grass.tools import Tools
tools = Tools()
tools.r_slope_aspect(elevation="elevation", slope="pilot_steep_slope")
tools.r_reclass(input="pilot_steep_slope", output="steep_areas", rules="0 thru 14 = 0\n15 thru 90 = 1")
tools.r_to_vect(input="steep_areas", output="pilot_steep", type="area")
