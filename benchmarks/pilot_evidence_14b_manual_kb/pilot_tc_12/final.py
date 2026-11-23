from grass.tools import Tools
tools = Tools()

# Compute shaded relief from the elevation raster
tools.r_relief(input="elevation", output="pilot_relief", azimuth=315, altitude=45)
