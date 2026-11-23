from grass.tools import Tools
tools = Tools()

# Compute shaded relief
tools.r_relief(input="elevation", output="pilot_relief", azimuth=315, altitude=45)
