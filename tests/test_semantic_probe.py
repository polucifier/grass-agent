"""Semantic probe parsing and failure modes with fake GRASS sessions (T012).

Every branch that could turn a real semantic failure into a silent pass is
covered here: a missing output, a stale map from an earlier attempt, zero
features, the wrong geometry, a missing column, zero non-null cells, a
non-finite statistic, a failed query, and both timeout kinds.
"""

import pytest

from grass_agent.semantic_probe import (
    ERROR_MISSING_OUTPUT,
    ERROR_NON_FINITE,
    ERROR_NO_VALUES,
    ERROR_PROBE_TIMEOUT,
    ERROR_QUERY_FAILED,
    ERROR_QUERY_TIMEOUT,
    ERROR_WRONG_TYPE,
    QueryResult,
    classify_geometry,
    evaluate_probe,
    feature_count,
    new_maps,
    parse_map_list,
    parse_univar,
    parse_v_info_columns,
    parse_v_info_topology,
    run_probe,
)


class FakeRunner:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, args, timeout_s):
        key = " ".join(args)
        self.calls.append(key)
        response = self.responses.get(key)
        if response is None:
            return QueryResult(stdout="", returncode=1, timed_out=False)
        if isinstance(response, QueryResult):
            return response
        return QueryResult(stdout=response, returncode=0, timed_out=False)


RASTER_SPEC = {
    "schema_version": 1,
    "case_id": "pilot_tc_x",
    "query_timeout_s": 30,
    "probe_timeout_s": 60,
    "outputs": [{"name": "pilot_r", "type": "raster"}],
    "assertions": [
        {"output": "pilot_r", "check": "non_null_count", "min": 1},
        {"output": "pilot_r", "check": "value_range", "min_value": 0, "max": 10},
        {"output": "pilot_r", "check": "mean", "expected": 5.0, "tolerance": 0.01},
    ],
}

VECTOR_SPEC = {
    "schema_version": 1,
    "case_id": "pilot_tc_y",
    "query_timeout_s": 30,
    "probe_timeout_s": 60,
    "outputs": [{"name": "pilot_v", "type": "vector", "geometry": "area"}],
    "assertions": [
        {"output": "pilot_v", "check": "feature_count", "min": 1},
        {"output": "pilot_v", "check": "geometry_type", "expected": "area"},
        {"output": "pilot_v", "check": "required_columns",
         "columns": ["cat", "GEO_NAME"]},
    ],
}


# --------------------------------------------------------------------------
# Parsers
# --------------------------------------------------------------------------


def test_parse_univar_reads_n_min_max_mean():
    parsed = parse_univar(
        "n=2025000\nnull_cells=0\nmin=55.5\nmax=156.3\nmean=110.37\n"
    )
    assert parsed == {"n": 2025000, "min": 55.5, "max": 156.3, "mean": 110.37}


def test_parse_univar_missing_key_raises():
    with pytest.raises(ValueError):
        parse_univar("n=1\nmin=0\nmax=1\n")


@pytest.mark.parametrize(
    "topology,expected",
    [
        ({"areas": 3, "lines": 0, "points": 0, "boundaries": 0}, "area"),
        ({"areas": 0, "lines": 3, "points": 0, "boundaries": 0}, "line"),
        ({"areas": 0, "lines": 0, "points": 3, "boundaries": 0}, "point"),
        ({"areas": 0, "lines": 0, "points": 0, "boundaries": 3}, "boundary"),
        ({"areas": 0, "lines": 0, "points": 0, "boundaries": 0}, "empty"),
    ],
)
def test_geometry_classification(topology, expected):
    assert classify_geometry(topology) == expected


def test_feature_count_uses_the_declared_geometry_counter():
    topology = {"areas": 7, "lines": 2, "points": 1, "centroids": 5,
                "primitives": 14}
    assert feature_count(topology, "area") == 7
    assert feature_count(topology, "line") == 2
    assert feature_count(topology, "point") == 1
    assert feature_count(topology, "boundary") == 5


def test_parse_v_info_columns_takes_the_last_field():
    text = "INTEGER|cat\nCHARACTER|GEO_NAME\nDOUBLE PRECISION|AREA\n"
    assert parse_v_info_columns(text) == ["cat", "GEO_NAME", "AREA"]


def test_parse_map_list_is_sorted_and_ignores_blank_lines():
    assert parse_map_list("b\n\n a \n") == ["a", "b"]


def test_new_maps_is_a_set_difference():
    before = {"raster": ["elevation"], "vector": ["streams"]}
    after = {"raster": ["elevation", "pilot_r"], "vector": ["streams"]}
    assert new_maps(before, after) == {"raster": ["pilot_r"], "vector": []}


# --------------------------------------------------------------------------
# Raster success and failure modes
# --------------------------------------------------------------------------


def _raster_runner(topology_text="n=10\nmin=0\nmax=10\nmean=5.0\n"):
    return FakeRunner({"r.univar -g -r map=pilot_r": topology_text})


def test_raster_assertions_pass():
    result = evaluate_probe(
        RASTER_SPEC, {"raster": ["pilot_r"], "vector": []}, runner=_raster_runner()
    )
    assert result["evaluated"] is True
    assert result["passed"] is True
    assert result["error"] is None
    assert [a["check"] for a in result["outputs"][0]["assertions"]] == [
        "non_null_count",
        "value_range",
        "mean",
    ]
    assert result["outputs"][0]["exists"] is True


def test_raster_mean_outside_tolerance_fails_with_evidence():
    runner = _raster_runner("n=10\nmin=0\nmax=10\nmean=8.0\n")
    result = evaluate_probe(RASTER_SPEC, {"raster": ["pilot_r"], "vector": []}, runner=runner)
    mean = [
        a for a in result["outputs"][0]["assertions"] if a["check"] == "mean"
    ][0]
    assert result["passed"] is False
    assert mean["passed"] is False
    assert mean["expected"] == 5.0
    assert mean["observed"] == 8.0
    assert mean["tolerance"] == 0.01


def test_raster_zero_non_null_cells_is_no_values():
    runner = _raster_runner("n=0\nmin=0\nmax=0\nmean=0\n")
    result = evaluate_probe(RASTER_SPEC, {"raster": ["pilot_r"], "vector": []}, runner=runner)
    assert result["error"] == ERROR_NO_VALUES
    assert result["passed"] is False


def test_raster_non_finite_value_is_a_failure():
    runner = _raster_runner("n=10\nmin=0\nmax=inf\nmean=5\n")
    result = evaluate_probe(RASTER_SPEC, {"raster": ["pilot_r"], "vector": []}, runner=runner)
    assert result["error"] == ERROR_NON_FINITE
    assert result["passed"] is False


def test_raster_query_failure_is_a_failure():
    runner = FakeRunner(
        {"r.univar -g -r map=pilot_r": QueryResult(stdout="", returncode=1)}
    )
    result = evaluate_probe(RASTER_SPEC, {"raster": ["pilot_r"], "vector": []}, runner=runner)
    assert result["error"] == ERROR_QUERY_FAILED
    assert result["passed"] is False


def test_raster_query_timeout_is_a_failure():
    runner = FakeRunner(
        {"r.univar -g -r map=pilot_r": QueryResult(timed_out=True, returncode=-1)}
    )
    result = evaluate_probe(RASTER_SPEC, {"raster": ["pilot_r"], "vector": []}, runner=runner)
    assert result["error"] == ERROR_QUERY_TIMEOUT
    assert result["passed"] is False


def test_probe_timeout_stops_before_querying():
    ticks = iter(range(0, 100, 10))

    def clock():
        return float(next(ticks))

    spec = dict(RASTER_SPEC, probe_timeout_s=1)
    result = evaluate_probe(
        spec,
        {"raster": ["pilot_r"], "vector": []},
        runner=_raster_runner(),
        clock=clock,
    )
    assert result["error"] == ERROR_PROBE_TIMEOUT
    assert result["passed"] is False


# --------------------------------------------------------------------------
# Vector success and failure modes
# --------------------------------------------------------------------------

_VECTOR_OK = {
    "v.info -t map=pilot_v": (
        "nodes=0\npoints=0\nlines=0\nboundaries=0\ncentroids=3\n"
        "areas=3\nislands=3\nprimitives=6\nmap3d=0\n"
    ),
    "v.info -c map=pilot_v": "INTEGER|cat\nCHARACTER|GEO_NAME\n",
}


def test_vector_assertions_pass():
    runner = FakeRunner(_VECTOR_OK)
    result = evaluate_probe(VECTOR_SPEC, {"raster": [], "vector": ["pilot_v"]}, runner=runner)
    assert result["passed"] is True
    assert result["error"] is None
    observed = result["outputs"][0]["observed"]
    assert observed["feature_count"] == 3
    assert observed["geometry"] == "area"
    assert observed["columns"] == ["cat", "GEO_NAME"]


def test_vector_zero_features_fails_feature_count():
    responses = dict(_VECTOR_OK)
    responses["v.info -t map=pilot_v"] = (
        "nodes=0\npoints=0\nlines=0\nboundaries=0\ncentroids=0\n"
        "areas=0\nislands=0\nprimitives=0\nmap3d=0\n"
    )
    result = evaluate_probe(
        VECTOR_SPEC, {"raster": [], "vector": ["pilot_v"]},
        runner=FakeRunner(responses),
    )
    feature = [
        a for a in result["outputs"][0]["assertions"] if a["check"] == "feature_count"
    ][0]
    assert feature["passed"] is False
    assert result["passed"] is False


def test_vector_wrong_geometry_fails():
    responses = dict(_VECTOR_OK)
    responses["v.info -t map=pilot_v"] = (
        "nodes=2\npoints=0\nlines=4\nboundaries=0\ncentroids=0\n"
        "areas=0\nislands=0\nprimitives=4\nmap3d=0\n"
    )
    result = evaluate_probe(
        VECTOR_SPEC, {"raster": [], "vector": ["pilot_v"]},
        runner=FakeRunner(responses),
    )
    geometry = [
        a for a in result["outputs"][0]["assertions"] if a["check"] == "geometry_type"
    ][0]
    assert geometry["passed"] is False
    assert geometry["observed"] == "line"


def test_vector_missing_column_fails():
    responses = dict(_VECTOR_OK)
    responses["v.info -c map=pilot_v"] = "INTEGER|cat\n"
    result = evaluate_probe(
        VECTOR_SPEC, {"raster": [], "vector": ["pilot_v"]},
        runner=FakeRunner(responses),
    )
    columns = [
        a for a in result["outputs"][0]["assertions"]
        if a["check"] == "required_columns"
    ][0]
    assert columns["passed"] is False
    assert "GEO_NAME" in columns["detail"]


def test_vector_without_attribute_table_fails_only_when_columns_declared():
    responses = dict(_VECTOR_OK)
    responses["v.info -c map=pilot_v"] = QueryResult(returncode=1)
    result = evaluate_probe(
        VECTOR_SPEC, {"raster": [], "vector": ["pilot_v"]},
        runner=FakeRunner(responses),
    )
    assert result["passed"] is False

    no_column_spec = dict(VECTOR_SPEC)
    no_column_spec["assertions"] = [
        a for a in VECTOR_SPEC["assertions"] if a["check"] != "required_columns"
    ]
    ok = evaluate_probe(
        no_column_spec, {"raster": [], "vector": ["pilot_v"]},
        runner=FakeRunner(responses),
    )
    assert ok["passed"] is True


# --------------------------------------------------------------------------
# Missing output and staleness (FR-008d)
# --------------------------------------------------------------------------


def test_missing_output_is_a_named_failure_not_a_skip():
    result = evaluate_probe(
        RASTER_SPEC, {"raster": [], "vector": []}, runner=_raster_runner()
    )
    assert result["error"] == ERROR_MISSING_OUTPUT
    assert result["outputs"][0]["exists"] is False
    assert result["outputs"][0]["assertions"]
    assert all(not a["passed"] for a in result["outputs"][0]["assertions"])


def test_wrong_type_output_is_named():
    result = evaluate_probe(
        RASTER_SPEC, {"raster": [], "vector": ["pilot_r"]}, runner=_raster_runner()
    )
    assert result["error"] == ERROR_WRONG_TYPE
    assert result["outputs"][0]["exists"] is False


def test_map_from_a_prior_attempt_is_never_credited(tmp_path):
    """FR-008d: attempt 1's map is in `before`; attempt 2 created nothing."""
    before = {"raster": [], "vector": []}
    after_attempt_1 = {"raster": ["pilot_r"], "vector": []}
    maps_out = tmp_path / "maps.json"
    semantic_out = tmp_path / "semantic.json"

    first = run_probe(
        RASTER_SPEC,
        before,
        after_attempt_1,
        runner=_raster_runner(),
        maps_out=maps_out,
        semantic_out=semantic_out,
    )
    assert first["passed"] is True

    # A later attempt only ever consults its own `after` snapshot. Even if the
    # name was present at attempt start (or in an earlier attempt's result), an
    # absent map cannot satisfy anything and is never credited.
    second = run_probe(
        RASTER_SPEC,
        after_attempt_1,
        {"raster": [], "vector": []},
        runner=_raster_runner(),
        maps_out=maps_out,
        semantic_out=semantic_out,
    )
    assert second["new_maps"] == {"raster": [], "vector": []}
    assert second["error"] == ERROR_MISSING_OUTPUT
    assert second["passed"] is False
