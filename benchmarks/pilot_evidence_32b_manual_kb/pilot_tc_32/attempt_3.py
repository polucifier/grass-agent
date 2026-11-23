from grass.tools import Tools
tools = Tools()
tools.r_slope_aspect(elevation="elevation", slope="pilot_steep_slope", format="degrees", precision="FCELL", zscale=1.0, min_slope=0.0, nprocs=0, memory=300)
tools.r_mapcalc(expression="steep_areas = if(pilot_steep_slope > 15, 1, null())")
rules = "1 = 1\n* = null()"
tools.r_reclass(input="steep_areas", output="steep_areas_reclassified", rules=rules)
tools.r_to_vect(input="steep_areas_reclassified", output="pilot_steep", type="area")
