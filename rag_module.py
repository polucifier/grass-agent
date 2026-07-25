import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm_provider import LLMProvider

SIMILARITY_THRESHOLD = 0.4

GRASS_KNOWLEDGE_BASE = [
    {
        "name": "change_raster_palette",
        "description": "Changes the color palette of a raster map in GRASS (using r.colors).",
        "keywords": "color, palette, raster, colors, style, look, dmt, dem, visualize, change styling"
    },
    {
        "name": "create_vector_buffer",
        "description": "Creates a buffer zone around a vector map with a specified distance (using v.buffer).",
        "keywords": "buffer, distance, vector, zone, area, road, river, surrounding, proximity"
    },
    {
        "name": "calculate_slope",
        "description": "Calculates slope and aspect from a digital elevation model / DEM (using r.slope.aspect).",
        "keywords": "slope, aspect, elevation, dmt, dem, terrain, steepness, hillshade, topography"
    }
]


def cosine_similarity(v1: list, v2: list) -> float:
    dot_product = sum(x * y for x, y in zip(v1, v2))
    magnitude1 = math.sqrt(sum(x * x for x in v1))
    magnitude2 = math.sqrt(sum(y * y for y in v2))
    if not magnitude1 or not magnitude2:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)


def retrieve_best_tool(user_query: str, provider: "LLMProvider", threshold: float = SIMILARITY_THRESHOLD):
    print(f"RAG: Analyzing user query: '{user_query}'...")

    try:
        query_vector = provider.generate_embeddings(user_query)
    except NotImplementedError:
        print("RAG: Embeddings not available for this provider. Cannot perform semantic search.")
        return None

    best_similarity = -1.0
    best_tool_name = None

    for tool in GRASS_KNOWLEDGE_BASE:
        tool_text = f"{tool['description']} {tool['keywords']}"
        try:
            tool_vector = provider.generate_embeddings(tool_text)
        except NotImplementedError:
            print("RAG: Embeddings not available for this provider. Cannot perform semantic search.")
            return None

        similarity = cosine_similarity(query_vector, tool_vector)

        if similarity > best_similarity:
            best_similarity = similarity
            best_tool_name = tool["name"]

    if best_similarity < threshold:
        print(f"RAG: No relevant tool found (best: '{best_tool_name}' at {best_similarity:.4f}, threshold: {threshold})")
        return None

    print(f"RAG: Most relevant tool identified: '{best_tool_name}' (similarity: {best_similarity:.4f})")
    return best_tool_name
