from grass.tools import Tools
tools = Tools()

# Calculate viewshed
tools.r_viewshed(input="elevation", output="pilot_viewshed", coordinates="635000,216500")
