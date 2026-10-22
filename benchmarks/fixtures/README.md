# Benchmark Fixtures — Gate 2 Auxiliary Inputs

Auxiliary inputs are the files a benchmark case references that do **not** exist in
the target GRASS dataset. Each one must be *declared* on the case via
`"auxiliary_inputs": []` and is staged into that attempt's scratch directory before
execution (FR-001b).

The harness never synthesises an undeclared file. If a generated script references a
name that is neither in the dataset nor declared here, that surfaces as a
`missing_input` failure — which is exactly what we want, because it means the model
got the name wrong rather than that the operator forgot to prepare something.

---

## 0. North Carolina dataset — one-time prerequisite

**This is provisioned manually by a human. The harness never downloads it (FR-016).**

The dataset is absent on a fresh host. Verified on the Gate 2 planning host: no
`nc_basic_spm*` on disk, `~/grassdata` empty, `grass-sample-data` package not installed.

```sh
mkdir -p ~/grassdata
curl -fL -o /tmp/nc.zip \
  https://grass.osgeo.org/sampledata/north_carolina/nc_basic_spm_grass7.zip
unzip -q /tmp/nc.zip -d ~/grassdata
ls ~/grassdata          # expect: nc_basic_spm_grass8/
```

> **The `_grass8` archive 404s.** `nc_basic_spm_grass8.zip` is not published; the live
> package is `nc_basic_spm_grass7.zip` (50 MB), which loads in GRASS 8.5 despite the name.

`nc_spm_08_grass7` (the 159 MB full dataset) is an accepted alternative — the harness
detects either. Auto-detection searches `$GISDBASE`, `$GRASSDATA`, `~/grassdata`, then
`./grassdata`; `--dataset PATH` overrides it.

### The PERMANENT write guard — apply once, keep it

```sh
chmod -w ~/grassdata/nc_basic_spm_grass8/PERMANENT
```

This is a **permanent, documented property of the provisioned fixture**, not a per-run
toggle. Nothing reverts it — not the harness, not teardown.

It exists because `grass --tmp-mapset` gives a generated script a writable *default
mapset*, not a sandbox. Verified: a script calling `g.mapset PERMANENT` can create
rasters that survive the session. Constitution Principle V and SC-002 require zero
mutation of the persistent mapset, so the guard is what makes that true. While the
write bit is absent, the `--tmp-mapset` workload was verified to run normally and
`g.mapset PERMANENT` fails non-zero.

Restore it only by hand (`chmod +w`) if you deliberately need to modify the dataset
outside this harness.

Verify:

```sh
grass --tmp-mapset ~/grassdata/nc_basic_spm_grass8/ \
  --exec python3 -c "from grass.tools import Tools; t=Tools(); print(list(t.grouped(type='raster')['PERMANENT'])[:3])"
```

---

## 1. CRS

All fixtures are **EPSG:3358** — NAD83(HARN) / North Carolina, Lambert Conformal Conic,
metres, `lat_0=33.75`, `lon_0=-79`, `x_0=609601.22` — identical to the CRS of
`nc_basic_spm_grass8` (verified with `g.proj -p`). A fixture in a different CRS would
fail to import, which would look like an agent error and corrupt the metrics.

## 2. Provenance

Generated in a throwaway GRASS project created with `grass -c EPSG:3358`, using
`v.random` with fixed seeds so the output is deterministic, then converted with `ogr2ogr`.
Shapefile siblings (`.shp`/`.shx`/`.dbf`/`.prj`) were produced together and must travel
as a set — declaring `boundary.shp` stages all four.

| File | Geometry | Features | CRS | Declared by |
|---|---|---|---|---|
| `points.geojson` | Point | 3 (`cat` 1–3) | EPSG:3358 | `tc_11` |
| `boundary.geojson` | Polygon | 1 | EPSG:3358 | — (GeoJSON twin of `boundary.shp`) |
| `boundary.shp/.shx/.dbf/.prj` | Polygon | 1 | EPSG:3358 | `tc_07` |
| `roads.shp/.shx/.dbf/.prj` | LineString | 8 | EPSG:3358 | `tc_03` |
| `schools.shp/.shx/.dbf/.prj` | Point | 5 | EPSG:3358 | `tc_29` |
| `dense_forest.geojson` | Polygon | 8 | EPSG:3358 | `tc_30` |
| `elevation.tif` | Raster (GeoTIFF) | 20×20 | EPSG:3358 | `tc_24` |
| `parcels.gpkg` | Polygon | 1 (`parcels`) | EPSG:3358 | `tc_25` |

Attribute columns carry `cat`, `name`, and one task-relevant field
(`label`, `type`, `density`) so prompts referencing a column resolve.

## 3. Regenerating

Fixtures are deterministic given their seeds. To rebuild, create a scratch project,
generate points/raster with the seeds above, and export with `v.out.ogr` /
`r.out.gdal` / `ogr2ogr`. Keep EPSG:3358 or the import will fail in a way that reads as
an agent failure rather than a fixture problem.