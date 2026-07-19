from fastmcp import FastMCP

# Inicializace MCP serveru s jasným názvem
mcp = FastMCP('GRASS-Server')

@mcp.tool()
def change_raster_palette(raster_name: str, palette: str) -> str:
    '''
    Změní barevnou paletu zadaného rastrového souboru v GRASS GIS.

    :param raster_name: Název rastrové vrstvy (např. "dem").
    :param palette: Název palety (např. "terrain", "srtm", "viridis").
    '''
    # Zatím pouze mock (simulace), později zde bude skutečné vnitřní API GRASSu
    print(f"\n[GRASS] Calling internal command: r.colors map={raster_name} color={palette}\n")
    return f"Success: Color palette of raster '{raster_name}' has been changed to '{palette}'."

@mcp.tool()
def create_vector_buffer(vector_name: str, distance: float) -> str:
    '''
    Vytvoří obalovou zónu (buffer) kolem zadané vektorové vrstvy.

    :param vector_name: Název vstupní vektorové vrstvy (např. "reky").
    :param distance: Šířka obalové zóny v metrech (např. 150.0).
    '''
    print(f"\n[GRASS] Calling internal command: v.buffer input={vector_name} distance={distance}\n")
    return f"Success: A buffer zone of {distance} meters was created around vector layer '{vector_name}'."

if __name__ == "__main__":
    mcp.run()
