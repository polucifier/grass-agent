from grass.tools import Tools
tools = Tools()

tools.v_dissolve(input="geology", output="pilot_geology_dissolved", column="GEO_NAME")
