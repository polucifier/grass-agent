# Benchmark Contamination Audit

Corpus: `data/grass_knowledge.db` (543 tool descriptions)  
Suites: `benchmark_prompts_tier1.json`, `benchmark_prompts_tier2.json`  
Similarity threshold: **0.35**

## Executive summary

| Metric | Value |
| --- | --- |
| Test cases audited | 40 |
| Mean Jaccard similarity | 0.163 |
| Maximum Jaccard similarity | 0.385 (`tc_04` vs `d.to.rast`) |
| Cases above threshold | 2 of 40 |
| Cases with a 3-gram match | 13 (total hits 113) |
| Cases with a 4-gram match | 5 (total hits 8) |
| Cases flagged POTENTIAL_LEAK | 1 of 40 |

**Overall verdict: POTENTIAL CONTAMINATION — investigate the flagged cases before quoting retrieval numbers.**

## Top overlaps

Ranked by Jaccard similarity against the single most similar tool description in the corpus.

| Test ID | Prompt excerpt | Most similar tool | Jaccard | Max n-gram match | Verdict |
| --- | --- | --- | --- | --- | --- |
| `tc_04` | Display the elevation raster map on the active monitor. | `d.to.rast` | 0.385 | 3-gram “elevation raster map” | CLEAN |
| `tc_02` | Calculate slope and aspect maps from the elevation raster. | `r.slope.aspect` | 0.357 | 3-gram “maps from the” | CLEAN |
| `tc_24` | Export the elevation raster map to an external GeoTIFF fi… | `r3.out.netcdf` | 0.267 | 3-gram “elevation raster map” | CLEAN |
| `tc_20` | Reclassify landcover raster into broad categories using r… | `r.reclass` | 0.250 | — | CLEAN |
| `tc_19` | Set raster cells with values below 0 to NULL in the bathy… | `r.null` | 0.231 | — | CLEAN |
| `tc_21` | Convert stream raster cells into vector line features. | `r.carve` | 0.214 | — | CLEAN |
| `tc_22` | Find the shortest route along a vector road network betwe… | `v.net.path` | 0.208 | — | CLEAN |
| `tc_09` | Multiply the elevation raster by 2 using raster map calcu… | `r.mapcalc` | 0.200 | — | CLEAN |
| `tc_25` | Export the parcels vector map to a GeoPackage file parcel… | `r3.out.netcdf` | 0.200 | 4-gram “vector map to a” | CLEAN |
| `tc_15` | Add a new double precision column named area_sqm to the p… | `db.dropcolumn` | 0.176 | — | CLEAN |

### Flagged cases

Each of these needs a human decision. A shared phrase may still be unavoidable if the prompt legitimately describes the very algorithm its expected tool implements, but the case should be confirmed as non-trivial before its score is quoted.

| Test ID | Jaccard | Evidence | Expected tool | Verdict |
| --- | --- | --- | --- | --- |
| `tc_35` | 0.174 | “using regularized spline with tension” (`r.resamp.rst`) | `v.surf.rst` | POTENTIAL_LEAK |

### Above threshold, judged clean

These score above the threshold yet are explained by domain vocabulary rather than a copied recipe. They are listed explicitly so that the judgement can be checked.

| Test ID | Jaccard | Most similar tool | Shared tokens | Why it is clean |
| --- | --- | --- | --- | --- |
| `tc_04` | 0.385 | `d.to.rast` | `active`, `display`, `map`, `monitor`, `raster` | similarity 0.385 > 0.35, but the overlap is domain vocabulary only |
| `tc_02` | 0.357 | `r.slope.aspect` | `aspect`, `elevation`, `maps`, `raster`, `slope` | similarity 0.357 > 0.35, but the overlap is domain vocabulary only |

## Methodological note

Two different kinds of overlap are being measured here, and only one of them is a problem.

**Expected domain vocabulary.** A prompt asking for a 200-metre buffer *must* share the token `buffer` with `v.buffer`, and a slope prompt *must* share `slope` with `r.slope`. This is the retrieval task working as intended: the query is supposed to use the same domain language as the documentation. Single shared domain words are therefore expected and are not evidence of contamination.

**Task recipe leakage.** The failure mode this audit exists to detect is different: a prompt that reproduces the *recipe* — a multi-word sequence of operations copied out of a tool description or example — so that a lexical or embedding retriever can match it almost perfectly without understanding anything. That inflates measured retrieval quality and would misstate the benchmark's difficulty.

A case is flagged `POTENTIAL_LEAK` on one of two independent grounds, and neither of them is the similarity score on its own.

1. **A verbatim, corpus-specific phrase.** Three or more consecutive words shared with a tool description or example, of which at least three are content words and all of those are infrequent in the corpus. Both conditions are needed. The content-word floor removes matches like "maps from the" and "in the attribute table", and the rarity test removes matches like "elevation raster map", whose words are ordinary even though they are three of them.
2. **High similarity plus rare corroboration.** A Jaccard score above the threshold together with at least two corpus-rare shared terms.

The phrase test is deliberately *not* gated on the similarity threshold. Jaccard is length-sensitive: a short prompt quoting one fragment of a long description scores low because the union is dominated by the description's other words. `tc_35` is the concrete case — it carries the strongest verbatim match in the suite yet scores only 0.174, and a threshold-first rule would have missed it.

Two known limits are worth stating. Document frequency is measured over 543 terse one-liners, so it understates how ordinary a term is outside the corpus; that is why the content-word floor carries part of the load. And a flag is a prompt for review, not a finding: where a prompt legitimately describes the algorithm its expected tool implements, some phrase overlap is unavoidable and the case is not invalid. Both biases push towards under-reporting, which is the safer direction for a benchmark audit.

Notes on the measures: Jaccard is computed on stop-word-free tokens, so function words do not inflate it, while n-gram matching keeps stop words so that a phrase match corresponds to words that were genuinely adjacent. A high Jaccard value is weak evidence on its own and should be read together with the n-gram column.

Generated by `scripts/audit_leakage.py`. Threshold 0.35.
