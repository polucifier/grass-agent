from grass.tools import Tools
tools = Tools()

tools.r_mapcalc(expression="pilot_elevation_double = elevation * 2")
