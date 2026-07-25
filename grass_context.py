from dataclasses import dataclass, field


@dataclass
class GRASSContext:
    location: str = "nc_spm_08"
    mapset: str = "PERMANENT"
    crs: str = "EPSG:3358"
    crs_description: str = "NC State Plane (meters)"
    region: dict = field(default_factory=lambda: {
        "n": 228500.0,
        "s": -32000.0,
        "e": 645000.0,
        "w": 220000.0,
        "nsres": 500.0,
        "ewres": 500.0,
    })
    rasters: list[str] = field(default_factory=lambda: [
        "elevation", "slope", "aspect", "landcover", "geology",
    ])
    vectors: list[str] = field(default_factory=lambda: [
        "roads", "rivers", "buildings", "parcels", "boundaries",
    ])

    def to_system_prompt_suffix(self) -> str:
        lines = [
            f"\nCurrent GRASS session:",
            f"  Location: {self.location}",
            f"  Mapset: {self.mapset}",
            f"  CRS: {self.crs} ({self.crs_description})",
            f"  Region bounds: N={self.region['n']}, S={self.region['s']}, E={self.region['e']}, W={self.region['w']}",
            f"  Resolution: {self.region['nsres']}m (ns) x {self.region['ewres']}m (ew)",
            f"  Available raster maps: {', '.join(self.rasters)}",
            f"  Available vector maps: {', '.join(self.vectors)}",
            "",
            "When creating output maps, use descriptive names like 'buffer_roads_100' or 'slope_elevation'.",
            "Buffer distances are in the CRS units (meters for this location).",
        ]
        return "\n".join(lines)
