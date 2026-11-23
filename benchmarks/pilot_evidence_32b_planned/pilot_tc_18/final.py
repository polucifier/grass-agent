from grass.tools import Tools
tools = Tools()
tools.v_dissolve(input="geology", column="GEO_NAME", output="pilot_geology_dissolved")
