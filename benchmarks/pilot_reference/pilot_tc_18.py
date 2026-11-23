"""Reference implementation for pilot_tc_18 (human-reviewed golden script).

The original benchmark task refers to parcels/zoning; the NC sample has no such
layer. The pilot keeps the same task class (polygon dissolve by attribute) on
the geology layer, as documented in research.md R9.
"""

from grass.tools import Tools

tools = Tools()
tools.v_dissolve(input="geology", output="pilot_geology_dissolved", column="GEO_NAME")
