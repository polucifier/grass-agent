from grass.tools import Tools
tools = Tools()

# Compute slope from the elevation raster
tools.r_slope_aspect(elevation="elevation", slope="pilot_slope")

# Generate 10-meter contour lines from the elevation raster
tools.r_contour(input="elevation", output="pilot_contours", step="10")
