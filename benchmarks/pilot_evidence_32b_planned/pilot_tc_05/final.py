from grass.tools import Tools
tools = Tools()
tools.r_slope_aspect(elevation="elevation", slope="pilot_slope", format="degrees", precision="FCELL", zscale=1.0, min_slope=0.0, nprocs=0, memory=300)
tools.r_contour(input="elevation", output="pilot_contours", step=10.0, cut=2)
