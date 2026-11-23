from grass.tools import Tools
tools = Tools()

# Calculate binary viewshed visibility from the elevation raster
tools.r_viewshed(
    input="elevation",
    output="pilot_viewshed",
    coordinates="635000,216500",
    observer_elevation=1.75,
    max_distance=-1,
    flags="b"
)
