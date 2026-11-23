from grass.tools import Tools
tools = Tools()
tools.r_viewshed(input="elevation", output="pilot_viewshed", coordinates="635000,216500", observer_elevation=1.75, flags="b")
