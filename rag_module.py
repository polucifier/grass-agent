import math
import ollama

# Naše lokální znalostní báze nástrojů a jejich popisů pro vyhledávání
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

def get_embedding(text: str) -> list:
    """Vygeneruje lokální vektor (embedding) pro zadaný text pomocí Ollamy."""
    response = ollama.embeddings(model="nomic-embed-text", prompt=text)
    return response["embedding"]

def cosine_similarity(v1: list, v2: list) -> float:
    """Spočítá kosinovou podobnost mezi dvěma vektory (čistý Python)."""
    dot_product = sum(x * y for x, y in zip(v1, v2))
    magnitude1 = math.sqrt(sum(x * x for x in v1))
    magnitude2 = math.sqrt(sum(y * y for y in v2))
    if not magnitude1 or not magnitude2:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)

def retrieve_best_tool(user_query: str):
    """
    Porovná dotaz uživatele se znalostní bází a vrátí nejrelevantnější nástroj.
    """
    print(f"🔍 RAG: Analyzing user query: '{user_query}'...")
    query_vector = get_embedding(user_query)

    best_similarity = -1.0
    best_tool_name = None

    for tool in GRASS_KNOWLEDGE_BASE:
        # Porovnáváme dotaz s popisem a klíčovými slovy nástroje
        tool_text = f"{tool['description']} {tool['keywords']}"
        tool_vector = get_embedding(tool_text)

        similarity = cosine_similarity(query_vector, tool_vector)
        # print(f"   -> Tool '{tool['name']}' similarity: {similarity:.4f}")

        if similarity > best_similarity:
            best_similarity = similarity
            best_tool_name = tool["name"]

    print(f"🎯 RAG: Most relevant tool identified: '{best_tool_name}' (similarity: {best_similarity:.4f})")
    return best_tool_name
