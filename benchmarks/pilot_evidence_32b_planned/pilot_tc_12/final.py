from grass.tools import Tools
tools = Tools()
tools.r_relief(input="elevation", output="pilot_relief", altitude=45, azimuth=315)
