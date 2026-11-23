from grass.tools import Tools
tools = Tools()
tools.r_viewshed(input="elevation", output="pilot_viewshed", coordinates="635000,216500", observer_elevation=1.75, target_elevation=0.0, max_distance=-1, refraction_coeff=0.14286, memory=500, flags="b")
