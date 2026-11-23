from grass.tools import Tools
tools = Tools()

tools.v_clean(
    input="roadsmajor",
    output="pilot_roads_clean",
    tool=["snap", "rmdupl"],
    threshold=1
)
