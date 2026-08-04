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
    "roads", "road", "river", "stream", "building", "parcel", "boundary",
    "line", "polygon", "point", "catchment", "watershed", "highway", "street",
    "zone", "vector", "bridge", "trail", "network",
]
RASTER_KEYWORDS = [
    "dem", "elevation", "raster", "slope", "hillshade", "landcover", "pixel",
    "grid", "ndvi", "satellite", "image", "terrain", "surface",
]
CATEGORY_BOOST = 0.15


def _category_boost(query: str, category: str) -> float:
    query = query.lower()
    if category == "v" and any(kw in query for kw in VECTOR_KEYWORDS):
        return CATEGORY_BOOST
    if category == "r" and any(kw in query for kw in RASTER_KEYWORDS):
        return CATEGORY_BOOST
    return 0.0


class GrassToolsRetriever:

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)

    def retrieve(self, query: str, query_embedding: list[float], k: int = 5) -> list[ToolDoc]:
        rows = self.conn.execute(
            "SELECT rowid, distance FROM tools_vec "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (sqlite_vec.serialize_float32(query_embedding), k * 3),
        ).fetchall()

        docs = []
        for rowid, distance in rows:
            row = self.conn.execute(
                "SELECT name, category, description, signature, example, params_json "
                "FROM tools WHERE rowid = ?",
                (rowid,),
            ).fetchone()
            if row is None:
                continue
            name, category, description, signature, example, params_json = row
            docs.append(ToolDoc(
                name=name,
                category=category,
                description=description,
                signature=signature,
                example=example,
                params=json.loads(params_json),
                similarity=1.0 - distance,
            ))

        docs.sort(
            key=lambda d: d.similarity + _category_boost(query, d.category),
            reverse=True,
        )
        return docs[:k]

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
