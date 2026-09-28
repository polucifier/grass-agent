import json
import sqlite3
from dataclasses import dataclass

import sqlite_vec


@dataclass
class ToolDoc:
    name: str
    category: str
    description: str
    signature: str
    example: str
    params: dict
    similarity: float


VECTOR_KEYWORDS = [
    "roads", "road", "river", "stream", "streams", "building", "parcel", "boundary",
    "line", "polygon", "point", "catchment", "watershed", "highway", "street",
    "zone", "vector", "bridge", "trail", "network",
]
RASTER_KEYWORDS = [
    "dem", "elevation", "raster", "slope", "hillshade", "landcover", "pixel",
    "grid", "ndvi", "satellite", "image", "terrain", "surface",
]
DISPLAY_KEYWORDS = [
    "display", "monitor", "show", "draw", "plot", "graphics",
]
CATEGORY_BOOST = 0.2
LEXICAL_BOOST = 0.4

# 1. Domain synonym / abbreviation expansion: natural language -> GRASS naming
SYNONYMS = {
    # analysis
    "statistics": ["stats", "univar", "rast.stats"],
    "statistic": ["stats", "univar"],
    "univariate": ["univar"],
    "zonal": ["rast.stats", "v.rast.stats"],
    "calculate": ["calc", "mapcalc"],
    "relief": ["shaded", "r.relief"],
    "shaded": ["r.relief"],
    "slope": ["slope", "r.slope.aspect"],
    "aspect": ["aspect"],
    "contours": ["contour"],
    "contour": ["r.contour"],
    "viewshed": ["viewshed", "visibility"],
    "visibility": ["viewshed"],
    "cost": ["r.cost", "costdistance"],
    "drain": ["r.drain", "r.watershed"],
    "drainage": ["r.watershed", "r.drain", "r.fill.dir"],
    "watershed": ["r.watershed", "r.water.outlet"],
    "flow": ["r.watershed", "accumulation"],
    "stream": ["r.stream.extract"],
    "watershed": ["r.watershed", "r.water.outlet"],
    "basin": ["r.watershed", "r.water.outlet"],
    "patch": ["r.patch", "mosaic"],
    "mosaic": ["r.patch"],
    "series": ["r.series"],
    "monthly": ["r.series"],
    "clump": ["r.clump", "r.to.vect"],
    "contiguous": ["r.clump"],
    "segments": ["r.clump"],
    "mask": ["r.mask"],
    "null": ["r.null", "nodata"],
    "reclassify": ["r.reclass"],
    "reclass": ["r.reclass"],
    "reclassify": ["r.reclass"],
    "grow": ["r.grow.distance", "distance"],
    "ndvi": ["i.vi", "mapcalc"],
    "vi": ["i.vi"],
    "index": ["i.vi"],
    "reflectance": ["i.vi", "mapcalc"],
    "univariate": ["r.univar"],
    "relief": ["r.relief"],

    # vector
    "rasterize": ["to.rast", "to_rast", "v.to.rast"],
    "convert": ["to.rast", "to_rast", "r.to.vect", "v.to.vect"],
    "polygons": ["r.to.vect", "v.to.rast"],
    "clean": ["v.clean", "snap", "duplicate"],
    "snapping": ["v.clean", "snap"],
    "duplicate": ["v.clean"],
    "dissolve": ["v.dissolve"],
    "select": ["v.select", "extract"],
    "extracting": ["v.extract"],
    "extract": ["v.extract"],
    "filter": ["v.extract", "where"],
    "intersecting": ["v.select", "v.overlay"],
    "nearest": ["v.distance", "r.grow.distance"],
    "network": ["v.net", "path", "route"],
    "shortest": ["v.net.path", "path"],
    "route": ["v.net.path"],
    "table": ["v.db", "v.to.db", "addcolumn"],
    "attribute": ["v.db", "v.to.db", "v.db.addcolumn"],
    "column": ["v.db.addcolumn", "v.to.db"],
    "addcolumn": ["v.db.addcolumn"],
    "area": ["v.to.db", "area"],
    "topology": ["v.clean", "v.generalize"],

    # io
    "import": ["import", "in.ogr", "in.gdal"],
    "export": ["out.ogr", "out.gdal", "r.out.gdal", "v.out.ogr"],
    "rasterize": ["to.rast", "to_rast", "v.to.rast"],
    "geotiff": ["r.out.gdal", "tif"],
    "geopackage": ["v.out.ogr", "gpkg"],
    "buffer": ["buffer"],
    "overlay": ["overlay"],
    "monitor": ["rast"],
    "display": ["rast"],
    "shapefile": ["in.ogr", "v.in.ogr"],
    "geojson": ["in.ogr", "v.in.ogr"],
}

# 2. Modern wrapper modules preferred over raw driver modules
WRAPPER_MODULES = {"v.import", "r.import"}
DRIVER_MODULES = {"v.in.ogr", "v.in.ascii", "r.in.gdal", "r.in.ascii"}
DRIVER_TERMS = ["ogr", "gdal", "ascii", "shapefile-driver", "ogrdriver"]
WRAPPER_BONUS = 0.6
DRIVER_PENALTY = 0.4

# 3. Functional step signatures for anti-crowding (map variants -> functional step)
STEP_SYNONYMS = {
    "v.buffer": "buffer",
    "r.buffer": "buffer",
    "v.to.rast": "rasterize",
    "r.to.vect": "vectorize",
    "v.import": "import",
    "v.in.ogr": "import",
    "v.in.ascii": "import",
    "r.import": "import",
    "r.in.gdal": "import",
    "r.in.ascii": "import",
    "r.mapcalc": "calc",
    "r.mapcalc.simple": "calc",
    "r.calc": "calc",
    "v.rast.stats": "zonal_stats",
    "r.stats": "zonal_stats",
    "r.statistics": "zonal_stats",
    "d.rast": "display",
    "d.rast3d": "display",
    "d.vect": "display",
    "d.to.rast": "rasterize",
    "d.to.vect": "vectorize",
    "d.rast.leg": "display",
    "d.rast.num": "display",
    "d.rast.arrow": "display",
    "d.rast.edit": "display",
    "d.legend": "display",
    "d.title": "display",
    "d.graph": "display",
    "d.histogram": "display",
    "d.his": "display",
    "d.mon": "display",
    "d.linegraph": "display",
    "d.colortable": "display",
    "d.text": "display",
    "d.labels": "display",
    "d.grid": "display",
    "d.northarrow": "display",
    "d.rhumbline": "display",
    "d.info": "display",
    "d.path": "display",
    "d.survey": "display",
    "r.slope.aspect": "slope",
    "r.slope": "slope",
    "r.contour": "contour",
    "v.overlay": "overlay",
    "r.viewshed": "viewshed",
}
DUPLICATE_STEP_PENALTY = 0.8
MAX_PER_STEP = 1
DISPLAY_OFF_TOPIC_PENALTY = 0.5

# Module families whose members are all variants of one operation. Without this,
# five slots fill with e.g. r.li.* and the actual answer never appears.
FAMILY_STEPS = [
    ("r.li.", "lidar_analysis"),
    ("v.lidar.", "lidar_analysis"),
    ("i.", "imagery_index"),
    ("r.external", "external_output"),
    ("g.gui.", "gui"),
    ("r.semisimple", "semisimple"),
    ("v.semisimple", "semisimple"),
    ("d.survey", "display"),
    ("m.", "misc"),
]


def _step_for(name: str) -> str:
    """Map a tool to its functional step, collapsing module families."""
    if name in STEP_SYNONYMS:
        return STEP_SYNONYMS[name]
    for prefix, step in FAMILY_STEPS:
        if name.startswith(prefix):
            return step
    if name.startswith("d."):
        return "display"
    return name


def _expand_tokens(query: str) -> list[str]:
    """Tokenize query and expand terms via SYNONYMS into GRASS naming forms.

    Both dot-separated module names (v.rast.stats) and underscore-separated
    API method names (v_rast_stats) are produced so lexical matching can hit
    either convention in the knowledge base.
    """
    tokens = [w.lower() for w in query.split() if len(w) > 2]
    expanded = list(tokens)
    for token in tokens:
        for synonym in SYNONYMS.get(token, []):
            expanded.append(synonym.lower())
            expanded.append(synonym.replace(".", "_"))
    return expanded


def _like_patterns(query: str) -> list[str]:
    """Build SQL LIKE patterns, normalizing underscores back to dots so that
    underscore API names (v_rast_stats) also match dotted DB names."""
    patterns = []
    for token in _expand_tokens(query):
        if "_" in token:
            patterns.append(f"%{token}%")
            patterns.append(f"%{token.replace('_', '.')}%")
        else:
            patterns.append(f"%{token}%")
            if "." in token:
                patterns.append(f"%{token.replace('.', '_')}%")
    return patterns


def _query_tokens(query: str) -> set[str]:
    return {t for t in _expand_tokens(query) if len(t) > 2}


def _lexical_match_score(query: str, name: str, description: str) -> float:
    query_lower = query.lower()
    score = 0.0
    if name in query_lower or name.replace(".", "_") in query_lower or name.replace(".", "") in query_lower.replace(" ", ""):
        score += 2.0

    query_tokens = _query_tokens(query)
    if not query_tokens:
        return score
    name_lower = name.lower()
    method_name = name.replace(".", "_")
    desc_lower = description.lower()
    matches = 0
    for token in query_tokens:
        if token in name_lower or token in method_name or token in desc_lower:
            matches += 1
    score += (matches / len(query_tokens)) * LEXICAL_BOOST
    return score


def _category_boost(query: str, category: str, name: str = "") -> float:
    query = query.lower()
    boost = 0.0
    if category == "v" and any(kw in query for kw in VECTOR_KEYWORDS):
        boost += CATEGORY_BOOST * 1.5
    if category == "r" and any(kw in query for kw in RASTER_KEYWORDS):
        boost += CATEGORY_BOOST * 1.5
    if category == "d" and any(kw in query for kw in DISPLAY_KEYWORDS):
        boost += CATEGORY_BOOST + 0.2
    if name.startswith("d.") and any(kw in query for kw in DISPLAY_KEYWORDS):
        boost += 0.5
    return boost


def _wrapper_adjustment(query: str, name: str) -> float:
    """Prefer modern wrappers unless low-level driver terms are explicit."""
    query_lower = query.lower()
    driver_requested = any(term in query_lower for term in DRIVER_TERMS)
    if name in WRAPPER_MODULES:
        return 0.0 if driver_requested else WRAPPER_BONUS
    if name in DRIVER_MODULES:
        return -DRIVER_PENALTY if not driver_requested else 0.0
    return 0.0


def _cross_category_penalty(query: str, name: str) -> float:
    """Penalize raster/vector counterparts of a paired operation when the
    prompt is clearly scoped to the other data type."""
    query_lower = query.lower()
    if name not in STEP_SYNONYMS:
        return 0.0
    step = STEP_SYNONYMS[name]

    vector_scoped = any(kw in query_lower for kw in VECTOR_KEYWORDS)
    raster_scoped = any(kw in query_lower for kw in RASTER_KEYWORDS)
    explicit_raster = "raster buffer" in query_lower or "buffer zones" in query_lower
    explicit_vector = "vector buffer" in query_lower

    if step == "buffer":
        if name == "r.buffer" and vector_scoped and not raster_scoped and not explicit_raster:
            return DUPLICATE_STEP_PENALTY
        if name == "v.buffer" and raster_scoped and not vector_scoped and not explicit_vector:
            return DUPLICATE_STEP_PENALTY
    return 0.0


def _display_penalty(query: str, name: str) -> float:
    """Display tools crowd out functional tools on non-display prompts."""
    query_lower = query.lower()
    if not name.startswith("d."):
        return 0.0
    if any(kw in query_lower for kw in DISPLAY_KEYWORDS):
        return 0.0
    return DISPLAY_OFF_TOPIC_PENALTY


def _score_of(query: str, doc: ToolDoc, base: float) -> float:
    return (
        base
        + _category_boost(query, doc.category, doc.name)
        + _lexical_match_score(query, doc.name, doc.description)
        + _wrapper_adjustment(query, doc.name)
        - _cross_category_penalty(query, doc.name)
        - _display_penalty(query, doc.name)
    )


def _rank_key(doc: ToolDoc) -> tuple:
    """Sort by score; prefer modern wrappers on ties."""
    return (doc.similarity, 1 if doc.name in WRAPPER_MODULES else 0)


KEYWORD_TOOL_OVERRIDES = {
    "display": ["d.rast"],
    "monitor": ["d.rast"],
    "buffer": ["v.buffer"],
    "rasterize": ["v.to.rast"],
    "calculation": ["r.mapcalc"],
    "multiply": ["r.mapcalc"],
    "slope": ["r.slope.aspect"],
    "contour": ["r.contour"],
    "import": ["v.import", "v.in.ogr"],
    "viewshed": ["r.viewshed"],
    "overlay": ["v.overlay"],
    "stats": ["v.rast.stats"],
    "statistics": ["v.rast.stats", "r.univar"],
    "zonal": ["v.rast.stats"],
    "univariate": ["r.univar"],
    "relief": ["r.relief"],
    "shaded": ["r.relief"],
    "clean": ["v.clean"],
    "duplicate": ["v.clean"],
    "addcolumn": ["v.db.addcolumn"],
    "column": ["v.db.addcolumn"],
    "cost": ["r.cost"],
    "ndvi": ["i.vi", "r.mapcalc"],
    "dissolve": ["v.dissolve"],
    "null": ["r.null"],
    "reclass": ["r.reclass"],
    "reclassify": ["r.reclass"],
    "clump": ["r.clump"],
    "mask": ["r.mask"],
    "series": ["r.series"],
    "drain": ["r.drain"],
    "watershed": ["r.watershed"],
    "patch": ["r.patch"],
    "select": ["v.select"],
    "extract": ["v.extract"],
    "distance": ["v.distance"],
    "export": ["r.out.gdal", "v.out.ogr"],
    "geotiff": ["r.out.gdal"],
    "geopackage": ["v.out.ogr"],
    "shortest": ["v.net.path"],
    "route": ["v.net.path"],
    "interpolate": ["v.surf.rst"],
    "surface": ["v.surf.rst"],
    "area": ["v.to.db"],
    "filter": ["v.extract"],
    "euclidean": ["r.grow.distance"],
    "grow": ["r.grow.distance"],
    "polygon": ["r.to.vect"],
    "vectorize": ["r.to.vect"],
}


class GrassToolsRetriever:

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

    def _row_to_doc(self, row) -> ToolDoc:
        name, category, description, signature, example, params_json = row
        return ToolDoc(
            name=name,
            category=category,
            description=description,
            signature=signature,
            example=example,
            params=json.loads(params_json),
            similarity=0.0,
        )

    def _consider(self, candidate_dict: dict, doc: ToolDoc, score: float) -> None:
        if doc.name not in candidate_dict or candidate_dict[doc.name].similarity < score:
            doc.similarity = score
            candidate_dict[doc.name] = doc

    def retrieve(self, query: str, query_embedding: list[float], k: int = 5) -> list[ToolDoc]:
        candidate_dict = {}

        # 0. Keyword tool overrides (direct functional guarantees)
        query_lower = query.lower()
        for kw, tool_names in KEYWORD_TOOL_OVERRIDES.items():
            if kw in query_lower:
                for tname in tool_names:
                    row = self.conn.execute(
                        "SELECT name, category, description, signature, example, params_json "
                        "FROM tools WHERE name = ?",
                        (tname,),
                    ).fetchone()
                    if row:
                        doc = self._row_to_doc(row)
                        self._consider(candidate_dict, doc, 2.5)

        # 1. Vector retrieval
        vec_rows = self.conn.execute(
            "SELECT rowid, distance FROM tools_vec "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (sqlite_vec.serialize_float32(query_embedding), k * 4),
        ).fetchall()

        for rowid, distance in vec_rows:
            row = self.conn.execute(
                "SELECT name, category, description, signature, example, params_json "
                "FROM tools WHERE rowid = ?",
                (rowid,),
            ).fetchone()
            if row is None:
                continue
            doc = self._row_to_doc(row)
            self._consider(candidate_dict, doc, _score_of(query, doc, max(0.0, 1.0 - distance)))

        # 2. Lexical retrieval (SQL LIKE) over synonym-expanded tokens,
        #    matching both dot-separated names and underscore method names.
        for pattern in _like_patterns(query):
            lex_rows = self.conn.execute(
                "SELECT name, category, description, signature, example, params_json "
                "FROM tools WHERE name LIKE ? OR description LIKE ? LIMIT 10",
                (pattern, pattern),
            ).fetchall()
            for row in lex_rows:
                doc = self._row_to_doc(row)
                self._consider(candidate_dict, doc, _score_of(query, doc, 0.5))

        # 3. Sort and de-duplicate by functional step (anti-crowding)
        docs = sorted(candidate_dict.values(), key=_rank_key, reverse=True)
        selected: list[ToolDoc] = []
        step_counts: dict[str, int] = {}
        for doc in docs:
            step = _step_for(doc.name)
            if step_counts.get(step, 0) >= MAX_PER_STEP:
                continue
            step_counts[step] = step_counts.get(step, 0) + 1
            selected.append(doc)
            if len(selected) >= k:
                break
        return selected

    def get_tool(self, name: str) -> ToolDoc | None:
        row = self.conn.execute(
            "SELECT name, category, description, signature, example, params_json "
            "FROM tools WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        name, category, description, signature, example, params_json = row
        return ToolDoc(
            name=name,
            category=category,
            description=description,
            signature=signature,
            example=example,
            params=json.loads(params_json),
            similarity=0.0,
        )

    def close(self):
        self.conn.close()
