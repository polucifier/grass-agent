from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP('GRASS-Server')


@mcp.tool(name="r.colors")
def r_colors(map: str, color: str) -> str:
    '''
    Changes the color palette of a raster map using r.colors.

    :param map: Name of the raster layer (e.g. "elevation").
    :param color: Color scheme: terrain, srtm, viridis, grey, etc.
    '''
    if not map or not map.strip():
        raise ToolError("map must be a non-empty string")
    if not color or not color.strip():
        raise ToolError("color must be a non-empty string")
    print(f"\n[GRASS] r.colors map={map} color={color}\n")
    return f"Success: Color palette of raster '{map}' changed to '{color}'."


@mcp.tool(name="v.buffer")
def v_buffer(input: str, output: str, distance: float) -> str:
    '''
    Creates a buffer zone around vector features with a specified distance using v.buffer.

    :param input: Name of input vector map (e.g. "roads").
    :param output: Name for output vector map (e.g. "buffer_roads_100").
    :param distance: Buffer distance in map units (meters).
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    if distance <= 0:
        raise ToolError(f"distance must be positive, got {distance}")
    print(f"\n[GRASS] v.buffer input={input} output={output} distance={distance}\n")
    return f"Success: A buffer zone of {distance} meters was created around vector layer '{input}'. Output: '{output}'."


@mcp.tool(name="r.slope.aspect")
def r_slope_aspect(elevation: str, slope: str, aspect: str = "") -> str:
    '''
    Calculates slope and aspect from a digital elevation model using r.slope.aspect.

    :param elevation: Name of input elevation raster (e.g. "elevation").
    :param slope: Name for output slope raster (e.g. "slope_elevation").
    :param aspect: Name for output aspect raster (optional).
    '''
    if not elevation or not elevation.strip():
        raise ToolError("elevation must be a non-empty string")
    if not slope or not slope.strip():
        raise ToolError("slope must be a non-empty string")
    cmd = f"r.slope.aspect elevation={elevation} slope={slope}"
    if aspect:
        cmd += f" aspect={aspect}"
    print(f"\n[GRASS] {cmd}\n")
    result = f"Success: Slope calculated from '{elevation}' and saved to '{slope}'."
    if aspect:
        result += f" Aspect saved to '{aspect}'."
    return result


@mcp.tool(name="r.info")
def r_info(map: str) -> str:
    '''
    Displays basic information about a raster map using r.info.

    :param map: Name of raster map to inspect.
    '''
    if not map or not map.strip():
        raise ToolError("map must be a non-empty string")
    print(f"\n[GRASS] r.info map={map}\n")
    return (
        f"Map: {map}\n"
        f"Type: raster\n"
        f"Rows: 521\nCols: 846\n"
        f"N: 228500.0 S: -32000.0 E: 645000.0 W: 220000.0\n"
        f"NS resolution: 500.0m EW resolution: 500.0m\n"
        f"Range: 55.58 to 1563.30\n"
        f"Units: meters"
    )


@mcp.tool(name="r.univar")
def r_univar(map: str) -> str:
    '''
    Calculates univariate statistics for a raster map using r.univar.

    :param map: Name of raster map to analyze.
    '''
    if not map or not map.strip():
        raise ToolError("map must be a non-empty string")
    print(f"\n[GRASS] r.univar map={map}\n")
    return (
        f"total null cells: 0\n"
        f"total cells: 440726\n"
        f"minimum: 55.57879\n"
        f"maximum: 1563.299\n"
        f"range: 1507.72\n"
        f"mean: 398.40\n"
        f"stddev: 238.32\n"
        f"variance: 56796.4"
    )


@mcp.tool(name="r.mapcalc")
def r_mapcalc(expression: str, output: str) -> str:
    '''
    Performs raster map algebra using r.mapcalc.

    :param expression: Mapcalc expression (e.g. "result = elevation * 3.28").
    :param output: Name for output raster.
    '''
    if not expression or not expression.strip():
        raise ToolError("expression must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] r.mapcalc expression=\"{expression}\" output={output}\n")
    return f"Success: Mapcalc executed. Output: '{output}'."


@mcp.tool(name="g.region")
def g_region(raster: str = "", vector: str = "", n: float = 0, s: float = 0, e: float = 0, w: float = 0) -> str:
    '''
    Views or sets the current geographic region using g.region.

    :param raster: Set region to match this raster.
    :param vector: Set region to match this vector.
    :param n: Northern boundary.
    :param s: Southern boundary.
    :param e: Eastern boundary.
    :param w: Western boundary.
    '''
    print(f"\n[GRASS] g.region\n")
    return (
        "projection: 99 (NC State Plane)\n"
        "zone:       0\n"
        "datum:      ** unknown (default: WGS84) **\n"
        "ellipsoid:  ** unknown (default: WGS84) **\n"
        "north:      228500.0\n"
        "south:      -32000.0\n"
        "west:       220000.0\n"
        "east:       645000.0\n"
        "nsres:      500.0\n"
        "ewres:      500.0\n"
        "rows:       521\n"
        "cols:       846\n"
    )


@mcp.tool(name="g.list")
def g_list(type: str = "raster", pattern: str = "*") -> str:
    '''
    Lists available GRASS data maps using g.list.

    :param type: Data type: raster, vector, raster_3d.
    :param pattern: Glob pattern to filter names.
    '''
    print(f"\n[GRASS] g.list type={type} pattern={pattern}\n")
    if type == "raster":
        return "elevation\nslope\naspect\nlandcover\ngeology"
    elif type == "vector":
        return "roads\nrivers\nbuildings\nparcels\nboundaries"
    return ""


@mcp.tool(name="g.gisenv")
def g_gisenv() -> str:
    '''
    Displays GRASS session environment variables using g.gisenv.
    '''
    print(f"\n[GRASS] g.gisenv\n")
    return (
        "LOCATION_NAME='nc_spm_08'\n"
        "GISDBASE='/home/user/grassdata'\n"
        "MAPSET='PERMANENT'"
    )


@mcp.tool(name="v.info")
def v_info(map: str) -> str:
    '''
    Displays basic information about a vector map using v.info.

    :param map: Name of vector map to inspect.
    '''
    if not map or not map.strip():
        raise ToolError("map must be a non-empty string")
    print(f"\n[GRASS] v.info map={map}\n")
    return (
        f"Map:      {map}\n"
        f"Mapset:   PERMANENT\n"
        f"Type:     vector (level 2)\n"
        f"Title:    {map}\n"
        f"Num features: 1356\n"
        f"Num areas:    0\n"
        f"N: 228500.0 S: -32000.0 E: 645000.0 W: 220000.0"
    )


@mcp.tool(name="v.overlay")
def v_overlay(input: str, overlay: str, output: str, operator: str = "and") -> str:
    '''
    Performs spatial overlay on two vector maps using v.overlay.

    :param input: Name of first vector map.
    :param overlay: Name of second vector map.
    :param output: Name for output vector map.
    :param operator: Operator: and, or, xor, not.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] v.overlay input={input} overlay={overlay} output={output} operator={operator}\n")
    return f"Success: Overlay '{operator}' performed on '{input}' and '{overlay}'. Output: '{output}'."


@mcp.tool(name="v.dissolve")
def v_dissolve(input: str, output: str, column: str = "") -> str:
    '''
    Dissolves vector features sharing the same category using v.dissolve.

    :param input: Name of input vector map.
    :param output: Name for output vector map.
    :param column: Column to dissolve by.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] v.dissolve input={input} output={output}\n")
    return f"Success: Features dissolved in '{input}'. Output: '{output}'."


@mcp.tool(name="v.extract")
def v_extract(input: str, output: str, where: str = "") -> str:
    '''
    Extracts features from a vector map based on a query using v.extract.

    :param input: Name of input vector map.
    :param output: Name for output vector map.
    :param where: SQL WHERE clause for attribute filter.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] v.extract input={input} output={output} where=\"{where}\"\n")
    return f"Success: Features extracted from '{input}'. Output: '{output}'."


@mcp.tool(name="v.to.rast")
def v_to_rast(input: str, output: str, use: str = "cat") -> str:
    '''
    Converts a vector map to a raster map using v.to.rast.

    :param input: Name of input vector map.
    :param output: Name for output raster map.
    :param use: What to rasterize: cat, val, attr, dir, label.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] v.to.rast input={input} output={output} use={use}\n")
    return f"Success: Vector '{input}' converted to raster '{output}'."


@mcp.tool(name="v.clean")
def v_clean(input: str, output: str, tool: str = "break") -> str:
    '''
    Cleans topology of vector maps using v.clean.

    :param input: Name of input vector map.
    :param output: Name for output vector map.
    :param tool: Cleaning tool: break, snap, rmbridge, etc.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] v.clean input={input} output={output} tool={tool}\n")
    return f"Success: Vector topology cleaned in '{input}'. Output: '{output}'."


@mcp.tool(name="r.resamp.stats")
def r_resamp_stats(input: str, output: str, method: str = "average") -> str:
    '''
    Resamples a raster map using aggregation with r.resamp.stats.

    :param input: Name of input raster.
    :param output: Name for output raster.
    :param method: Aggregation method: average, sum, min, max, median.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] r.resamp.stats input={input} output={output} method={method}\n")
    return f"Success: Raster '{input}' resampled to '{output}' using {method}."


@mcp.tool(name="r.cost")
def r_cost(input: str, output: str, start_points: str = "") -> str:
    '''
    Calculates cost-distance from points using r.cost.

    :param input: Name of cost surface raster.
    :param output: Name for output cost raster.
    :param start_points: Vector map of start points.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] r.cost input={input} output={output}\n")
    return f"Success: Cost distance calculated. Output: '{output}'."


@mcp.tool(name="v.surf.rst")
def v_surf_rst(input: str, output: str) -> str:
    '''
    Interpolates a raster surface from points using regularized spline (v.surf.rst).

    :param input: Name of input point vector map.
    :param output: Name for output raster map.
    '''
    if not input or not input.strip():
        raise ToolError("input must be a non-empty string")
    if not output or not output.strip():
        raise ToolError("output must be a non-empty string")
    print(f"\n[GRASS] v.surf.rst input={input} output={output}\n")
    return f"Success: Surface interpolated from '{input}'. Output: '{output}'."


@mcp.tool(name="d.rast")
def d_rast(map: str) -> str:
    '''
    Displays a raster map using d.rast.

    :param map: Name of raster map to display.
    '''
    if not map or not map.strip():
        raise ToolError("map must be a non-empty string")
    print(f"\n[GRASS] d.rast map={map}\n")
    return f"Success: Displaying raster '{map}'."


@mcp.tool(name="d.vect")
def d_vect(map: str, color: str = "black") -> str:
    '''
    Displays a vector map using d.vect.

    :param map: Name of vector map to display.
    :param color: Display color.
    '''
    if not map or not map.strip():
        raise ToolError("map must be a non-empty string")
    print(f"\n[GRASS] d.vect map={map} color={color}\n")
    return f"Success: Displaying vector '{map}' in {color}."


if __name__ == "__main__":
    mcp.run(transport="stdio")
