from grass.tools import Tools
tools = Tools()

# Create a vector map of the current region extent
tools.v_in_region(output="region_polygon")

# Dissolve adjacent geology polygons that share the same GEO_NAME attribute
tools.v_dissolve(input="geology", layer="1", column="GEO_NAME", output="pilot_geology_dissolved")
