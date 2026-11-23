from grass.tools import Tools
tools = Tools()
tools.r_slope_aspect(elevation="elevation", slope="pilot_slope")
tools.r_contour(input="elevation", output="pilot_contours", step=10)
