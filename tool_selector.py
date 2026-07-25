import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_provider import LLMProvider


@dataclass
class ToolDef:
    name: str
    description: str
    category: str
    keywords: list[str]
    parameters: dict
    examples: list[str] = field(default_factory=list)


TOOL_REGISTRY: list[ToolDef] = [
    # ── Raster analysis ──────────────────────────────────────────────
    ToolDef(
        name="r.slope.aspect",
        description="Calculates slope and aspect from a digital elevation model.",
        category="raster",
        keywords=["slope", "aspect", "elevation", "dem", "terrain", "steepness", "hillshade", "topography"],
        parameters={
            "elevation": {"type": "string", "required": True, "description": "Name of input elevation raster"},
            "slope": {"type": "string", "required": False, "description": "Name for output slope raster"},
            "aspect": {"type": "string", "required": False, "description": "Name for output aspect raster"},
        },
        examples=["calculate slope from dem", "get aspect of elevation", "terrain analysis"],
    ),
    ToolDef(
        name="r.mapcalc",
        description="Raster map algebra. Performs cell-by-cell arithmetic on raster maps.",
        category="raster",
        keywords=["mapcalc", "algebra", "calculate", "math", "formula", "expression", "raster", "compute"],
        parameters={
            "expression": {"type": "string", "required": True, "description": "Mapcalc expression, e.g. 'result = elev * 3.28'"},
            "output": {"type": "string", "required": True, "description": "Name for output raster"},
        },
        examples=["multiply elevation by 3.28", "calculate ndvi", "reclassify raster"],
    ),
    ToolDef(
        name="r.univar",
        description="Calculates univariate statistics (min, max, mean, stddev) for a raster map.",
        category="raster",
        keywords=["statistics", "stats", "mean", "min", "max", "stddev", "summary", "describe", "info"],
        parameters={
            "map": {"type": "string", "required": True, "description": "Name of raster map to analyze"},
        },
        examples=["statistics of elevation", "describe dem", "what is the mean value"],
    ),
    ToolDef(
        name="r.colors",
        description="Changes the color palette of a raster map for visualization.",
        category="raster",
        keywords=["color", "palette", "colormap", "style", "visualize", "render", "display"],
        parameters={
            "map": {"type": "string", "required": True, "description": "Name of raster map"},
            "color": {"type": "string", "required": True, "description": "Color scheme: terrain, srtm, viridis, grey, etc."},
        },
        examples=["change colors to terrain", "apply viridis palette", "colorize dem"],
    ),
    ToolDef(
        name="r.resamp.stats",
        description="Resamples a raster map to a finer or coarser resolution using aggregation.",
        category="raster",
        keywords=["resample", "resolution", "aggregate", "resize", "rescale", "coarser", "finer"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input raster"},
            "output": {"type": "string", "required": True, "description": "Name for output raster"},
            "method": {"type": "string", "required": False, "description": "Aggregation method: average, sum, min, max, median"},
        },
        examples=["resample to 100m", "make coarser resolution", "aggregate raster"],
    ),
    ToolDef(
        name="r.grow",
        description="Grows a raster map by one cell in all directions, optionally with distance.",
        category="raster",
        keywords=["grow", "expand", "dilate", "buffer raster", "spread"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input raster"},
            "output": {"type": "string", "required": True, "description": "Name for output raster"},
            "distance": {"type": "float", "required": False, "description": "Distance to grow in map units"},
        },
        examples=["grow raster by 50 meters", "expand cells"],
    ),
    ToolDef(
        name="r.clump",
        description="Finds clumps (connected regions) of non-zero cells in a raster map.",
        category="raster",
        keywords=["clump", "group", "cluster", "regions", "connected", "patches", "areas"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input raster"},
            "output": {"type": "string", "required": True, "description": "Name for output raster"},
        },
        examples=["find clumps", "group connected areas", "identify patches"],
    ),
    ToolDef(
        name="r.distance",
        description="Calculates distances between features in a raster or vector map.",
        category="raster",
        keywords=["distance", "nearest", "proximity", "far", "close", "away"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input raster or vector"},
        },
        examples=["calculate distances", "find nearest features", "proximity analysis"],
    ),
    ToolDef(
        name="r.info",
        description="Displays basic information about a raster map (extent, resolution, type).",
        category="raster",
        keywords=["info", "information", "metadata", "describe", "properties", "extent", "bounds"],
        parameters={
            "map": {"type": "string", "required": True, "description": "Name of raster map"},
        },
        examples=["show info about dem", "describe raster properties", "what is this raster"],
    ),

    # ── Vector analysis ──────────────────────────────────────────────
    ToolDef(
        name="v.buffer",
        description="Creates a buffer zone around vector features with a specified distance.",
        category="vector",
        keywords=["buffer", "distance", "zone", "area", "proximity", "surround", "around", "ring"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output vector map"},
            "distance": {"type": "float", "required": True, "description": "Buffer distance in map units (meters)"},
        },
        examples=["buffer roads by 100 meters", "create zone around rivers", "surround buildings"],
    ),
    ToolDef(
        name="v.info",
        description="Displays basic information about a vector map (type, features, extent).",
        category="vector",
        keywords=["info", "information", "metadata", "describe", "properties", "count", "features"],
        parameters={
            "map": {"type": "string", "required": True, "description": "Name of vector map"},
        },
        examples=["show info about roads", "describe vector properties", "how many features"],
    ),
    ToolDef(
        name="v.clean",
        description="Cleans topology of vector maps. Removes overlaps, corrects boundaries.",
        category="vector",
        keywords=["clean", "topology", "fix", "repair", "overlap", "boundary", "snap", "break"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output vector map"},
            "tool": {"type": "string", "required": False, "description": "Cleaning tool: break, snap, rmbridge, etc."},
        },
        examples=["clean vector topology", "fix overlaps", "repair boundaries"],
    ),
    ToolDef(
        name="v.overlay",
        description="Performs spatial overlay (intersection, union, XOR) on two vector maps.",
        category="vector",
        keywords=["overlay", "intersection", "union", "xor", "clip", "spatial", "combine", "merge"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of first vector map (A)"},
            "overlay": {"type": "string", "required": True, "description": "Name of second vector map (B)"},
            "output": {"type": "string", "required": True, "description": "Name for output vector map"},
            "operator": {"type": "string", "required": True, "description": "Operator: and, or, xor, not"},
        },
        examples=["intersect roads with parcels", "overlay layers", "clip vectors"],
    ),
    ToolDef(
        name="v.dissolve",
        description="Dissolves (merges) vector features sharing the same category value.",
        category="vector",
        keywords=["dissolve", "merge", "combine", "aggregate", "unify", "join"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output vector map"},
            "column": {"type": "string", "required": False, "description": "Column to dissolve by"},
        },
        examples=["dissolve polygons", "merge features by category", "combine regions"],
    ),
    ToolDef(
        name="v.centroids",
        description="Adds centroid features to areas (polygons) in a vector map.",
        category="vector",
        keywords=["centroid", "center", "point", "area", "polygon", "middle"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output vector map"},
        },
        examples=["add centroids to polygons", "calculate centers of areas"],
    ),
    ToolDef(
        name="v.to.rast",
        description="Converts a vector map to a raster map.",
        category="vector",
        keywords=["convert", "rasterize", "vector to raster", "export", "write"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output raster map"},
            "use": {"type": "string", "required": False, "description": "What to rasterize: attr, cat, val, dir, label"},
        },
        examples=["convert vector to raster", "rasterize polygons", "vector to raster"],
    ),
    ToolDef(
        name="v.extract",
        description="Extracts features from a vector map based on category or attribute query.",
        category="vector",
        keywords=["extract", "select", "filter", "subset", "query", "where", "sql"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output vector map"},
            "where": {"type": "string", "required": False, "description": "SQL WHERE clause for attribute filter"},
        },
        examples=["extract roads of type highway", "select buildings", "filter by attribute"],
    ),
    ToolDef(
        name="v.category",
        description="Manages category values (IDs) of vector features.",
        category="vector",
        keywords=["category", "cat", "id", "reassign", "add", "remove", "layer"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output vector map"},
            "operation": {"type": "string", "required": True, "description": "Operation: add, del, chlayer, sum, report"},
        },
        examples=["add categories", "reassign ids", "report categories"],
    ),

    # ── General / session ────────────────────────────────────────────
    ToolDef(
        name="g.region",
        description="Views or sets the current geographic region (computational window).",
        category="general",
        keywords=["region", "extent", "bounds", "window", "area", "viewport", "zoom"],
        parameters={
            "raster": {"type": "string", "required": False, "description": "Set region to match this raster"},
            "vector": {"type": "string", "required": False, "description": "Set region to match this vector"},
            "n": {"type": "float", "required": False, "description": "Northern boundary"},
            "s": {"type": "float", "required": False, "description": "Southern boundary"},
            "e": {"type": "float", "required": False, "description": "Eastern boundary"},
            "w": {"type": "float", "required": False, "description": "Western boundary"},
        },
        examples=["show current region", "set region to match dem", "zoom to area"],
    ),
    ToolDef(
        name="g.list",
        description="Lists available GRASS data maps (rasters, vectors, etc.) in the current mapset.",
        category="general",
        keywords=["list", "maps", "available", "show", "display", "files", "data"],
        parameters={
            "type": {"type": "string", "required": False, "description": "Data type: raster, vector, raster_3d"},
            "pattern": {"type": "string", "required": False, "description": "Glob pattern to filter names"},
        },
        examples=["list all rasters", "show available vectors", "what data do i have"],
    ),
    ToolDef(
        name="g.gisenv",
        description="Displays or sets GRASS session environment variables.",
        category="general",
        keywords=["env", "environment", "session", "gisdb", "location", "mapset", "settings"],
        parameters={},
        examples=["show current location", "what mapset am i in", "show session info"],
    ),
    ToolDef(
        name="g.rename",
        description="Renames a GRASS data map.",
        category="general",
        keywords=["rename", "rename map", "change name"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Current name of the map"},
            "output": {"type": "string", "required": True, "description": "New name for the map"},
            "type": {"type": "string", "required": True, "description": "Map type: raster, vector"},
        },
        examples=["rename raster map", "change map name"],
    ),
    ToolDef(
        name="g.copy",
        description="Copies a GRASS data map.",
        category="general",
        keywords=["copy", "duplicate", "clone", "backup"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of map to copy"},
            "output": {"type": "string", "required": True, "description": "Name for the copy"},
            "type": {"type": "string", "required": True, "description": "Map type: raster, vector"},
        },
        examples=["copy raster map", "duplicate vector"],
    ),
    ToolDef(
        name="g.remove",
        description="Removes (deletes) GRASS data maps.",
        category="general",
        keywords=["remove", "delete", "drop", "purge", "erase"],
        parameters={
            "name": {"type": "string", "required": True, "description": "Name of map to remove"},
            "type": {"type": "string", "required": True, "description": "Map type: raster, vector"},
        },
        examples=["delete raster", "remove vector map", "erase map"],
    ),

    # ── Display ──────────────────────────────────────────────────────
    ToolDef(
        name="d.rast",
        description="Displays a raster map in the current graphics monitor.",
        category="display",
        keywords=["display", "show", "render", "plot", "map", "raster", "view"],
        parameters={
            "map": {"type": "string", "required": True, "description": "Name of raster map to display"},
        },
        examples=["display dem", "show raster map", "render elevation"],
    ),
    ToolDef(
        name="d.vect",
        description="Displays a vector map in the current graphics monitor.",
        category="display",
        keywords=["display", "show", "render", "plot", "map", "vector", "view"],
        parameters={
            "map": {"type": "string", "required": True, "description": "Name of vector map to display"},
            "color": {"type": "string", "required": False, "description": "Display color"},
        },
        examples=["display roads", "show vector map", "render buildings"],
    ),
    ToolDef(
        name="d.mon",
        description="Opens or closes a graphics monitor for display.",
        category="display",
        keywords=["monitor", "window", "display", "open", "close", "screen"],
        parameters={
            "start": {"type": "string", "required": False, "description": "Monitor to start: x0, wxgui, etc."},
            "stop": {"type": "string", "required": False, "description": "Monitor to stop"},
        },
        examples=["open display window", "start monitor", "close display"],
    ),
    ToolDef(
        name="d.out.file",
        description="Exports the current display to a graphics file (PNG, PDF, etc.).",
        category="display",
        keywords=["export", "save", "output", "png", "pdf", "image", "screenshot"],
        parameters={
            "output": {"type": "string", "required": True, "description": "Output file name (with extension)"},
            "format": {"type": "string", "required": False, "description": "Format: png, pdf, tif"},
        },
        examples=["export display to png", "save map as image", "screenshot"],
    ),

    # ── Analysis ─────────────────────────────────────────────────────
    ToolDef(
        name="r.cost",
        description="Calculates cost-distance (least cost path) from points on a cost surface.",
        category="analysis",
        keywords=["cost", "distance", "path", "least cost", "travel", "friction", "surface"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of cost surface raster"},
            "output": {"type": "string", "required": True, "description": "Name for output cost raster"},
            "start_points": {"type": "string", "required": False, "description": "Vector map of start points"},
        },
        examples=["calculate cost distance", "find least cost path", "travel cost analysis"],
    ),
    ToolDef(
        name="r.surf.idw",
        description="Interpolates a raster surface from points using inverse distance weighting.",
        category="analysis",
        keywords=["interpolate", "idw", "surface", "points", "survey", "kriging", "weighted"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input point vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output raster map"},
            "power": {"type": "float", "required": False, "description": "Power for IDW (default 2)"},
        },
        examples=["interpolate surface from points", "create raster from survey data", "idw interpolation"],
    ),
    ToolDef(
        name="v.surf.rst",
        description="Interpolates a raster surface from vector points using regularized spline with tension.",
        category="analysis",
        keywords=["spline", "interpolate", "surface", "tension", "rst", "continuous", "smooth"],
        parameters={
            "input": {"type": "string", "required": True, "description": "Name of input point vector map"},
            "output": {"type": "string", "required": True, "description": "Name for output raster map"},
        },
        examples=["spline interpolation", "create smooth surface", "interpolate with tension"],
    ),
]


class ToolSelector:

    def __init__(self, provider: "LLMProvider", threshold: float = 0.4):
        self.provider = provider
        self.threshold = threshold
        self.registry = TOOL_REGISTRY
        self._keyword_index: dict[str, set[str]] = {}
        self._category_index: dict[str, set[str]] = {}
        self._build_indexes()

    def _build_indexes(self):
        for tool in self.registry:
            for kw in tool.keywords:
                self._keyword_index.setdefault(kw.lower(), set()).add(tool.name)
            self._category_index.setdefault(tool.category, set()).add(tool.name)

    def _keyword_filter(self, query: str) -> list[ToolDef]:
        words = query.lower().split()
        matched_names: set[str] = set()
        for word in words:
            if word in self._keyword_index:
                matched_names.update(self._keyword_index[word])
            # Also check partial matches (e.g. "buffering" matches "buffer")
            for kw, names in self._keyword_index.items():
                if kw in word or word in kw:
                    matched_names.update(names)
        return [t for t in self.registry if t.name in matched_names]

    def _semantic_rank(self, query: str, candidates: list[ToolDef]) -> list[ToolDef]:
        if not candidates:
            return []

        try:
            query_vec = self.provider.generate_embeddings(query)
        except NotImplementedError:
            return candidates[:15]

        scored: list[tuple[float, ToolDef]] = []
        for tool in candidates:
            tool_text = f"{tool.description} {' '.join(tool.keywords)} {' '.join(tool.examples)}"
            try:
                tool_vec = self.provider.generate_embeddings(tool_text)
                sim = _cosine_similarity(query_vec, tool_vec)
            except NotImplementedError:
                sim = 0.5
            scored.append((sim, tool))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Return top tools above threshold, or top 5 as fallback
        above = [tool for _, tool in scored if scored[0][0] >= self.threshold]
        if above:
            return above[:15]
        return [tool for _, tool in scored[:5]]

    def select_tools(self, query: str, max_tools: int = 15) -> list[ToolDef]:
        candidates = self._keyword_filter(query)

        if not candidates:
            candidates = list(self.registry)

        ranked = self._semantic_rank(query, candidates)
        return ranked[:max_tools] if ranked else candidates[:max_tools]

    def get_all_tool_names(self) -> list[str]:
        return [t.name for t in self.registry]


def _cosine_similarity(v1: list, v2: list) -> float:
    dot = sum(x * y for x, y in zip(v1, v2))
    m1 = math.sqrt(sum(x * x for x in v1))
    m2 = math.sqrt(sum(y * y for y in v2))
    if not m1 or not m2:
        return 0.0
    return dot / (m1 * m2)
