"""Auxiliary input resolution and staging (task T037).

The behaviour that matters is the refusal: the harness must never invent a file
that a case did not declare, because doing so would silently convert an agent
error into a pass.
"""

import pytest

from grass_agent.fixtures import (
    FixtureError,
    filter_cases,
    load_suite,
    required_fixtures,
    resolve_fixture,
    stage_fixtures,
    unmatched_ids,
)

SHAPEFILE_COMPONENTS = {".shp", ".shx", ".dbf", ".prj"}


@pytest.fixture
def fixtures_dir(tmp_path):
    """A small fixture registry: one shapefile set plus one plain file."""
    root = tmp_path / "fixtures"
    root.mkdir()
    for suffix in SHAPEFILE_COMPONENTS:
        (root / f"boundary{suffix}").write_bytes(b"\x00" * 8)
    (root / "points.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    return root


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def test_bare_filename_resolves(fixtures_dir):
    assert [p.name for p in resolve_fixture(fixtures_dir, "points.geojson")] == [
        "points.geojson"
    ]


def test_shapefile_stem_expands_to_all_siblings(fixtures_dir):
    """All four components must travel together or the import fails."""
    resolved = {p.name for p in resolve_fixture(fixtures_dir, "boundary.shp")}
    assert resolved == {"boundary.shp", "boundary.shx", "boundary.dbf", "boundary.prj"}


def test_shapefile_expansion_is_order_independent(fixtures_dir):
    """Declaring .shx or .dbf directly resolves the same set."""
    via_shx = {p.name for p in resolve_fixture(fixtures_dir, "boundary.shx")}
    via_dbf = {p.name for p in resolve_fixture(fixtures_dir, "boundary.dbf")}
    assert via_shx == via_dbf


def test_absolute_path_is_rejected(fixtures_dir):
    with pytest.raises(FixtureError, match="absolute"):
        resolve_fixture(fixtures_dir, "/etc/passwd")


def test_parent_traversal_is_rejected(fixtures_dir):
    """Normalisation must happen before the containment check."""
    with pytest.raises(FixtureError, match="escapes"):
        resolve_fixture(fixtures_dir, "../../secret.txt")
    with pytest.raises(FixtureError, match="escapes"):
        resolve_fixture(fixtures_dir, "sub/../../secret.txt")


def test_empty_name_is_rejected(fixtures_dir):
    with pytest.raises(FixtureError):
        resolve_fixture(fixtures_dir, "  ")


def test_missing_fixture_resolves_empty_not_error(fixtures_dir):
    """Absence is reported by an empty list, letting the caller decide.

    Pre-flight treats it as fatal; the per-attempt path treats it as a
    missing_input failure. Both need the same resolver.
    """
    assert resolve_fixture(fixtures_dir, "nope.geojson") == []


# --------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------


def test_staging_copies_rather_than_moves(fixtures_dir, tmp_path):
    """Originals are the operator's provisioning and must survive."""
    scratch = tmp_path / "scratch"
    stage_fixtures(fixtures_dir, scratch, ["points.geojson", "boundary.shp"])

    assert (fixtures_dir / "points.geojson").is_file()
    assert (fixtures_dir / "boundary.shp").is_file()
    assert (scratch / "points.geojson").is_file()
    for suffix in SHAPEFILE_COMPONENTS:
        assert (scratch / f"boundary{suffix}").is_file()


def test_staged_content_matches_source(fixtures_dir, tmp_path):
    scratch = tmp_path / "scratch"
    stage_fixtures(fixtures_dir, scratch, ["points.geojson"])
    assert (scratch / "points.geojson").read_text() == (
        fixtures_dir / "points.geojson"
    ).read_text()


def test_staging_undeclared_file_raises(fixtures_dir, tmp_path):
    """An undeclared file must never be synthesised (FR-001b).

    The name may or may not exist; the point is that staging only ever copies
    something the operator provisioned and the case declared.
    """
    with pytest.raises(FixtureError, match="not found"):
        stage_fixtures(fixtures_dir, tmp_path / "scratch", ["undeclared.geojson"])


def test_staging_creates_scratch_dir(fixtures_dir, tmp_path):
    scratch = tmp_path / "deep" / "scratch"
    stage_fixtures(fixtures_dir, scratch, ["points.geojson"])
    assert scratch.is_dir()


# --------------------------------------------------------------------------
# Suite helpers
# --------------------------------------------------------------------------


def test_required_fixtures_flattens_case_and_name():
    cases = [
        {"id": "tc_01", "auxiliary_inputs": ["a.geojson", "b.shp"]},
        {"id": "tc_02", "auxiliary_inputs": []},
        {"id": "tc_03"},
    ]
    assert required_fixtures(cases) == [("tc_01", "a.geojson"), ("tc_01", "b.shp")]


def test_required_fixtures_tolerates_missing_key():
    assert required_fixtures([{"id": "tc_01"}]) == []


def test_filter_cases_preserves_suite_order():
    cases = [{"id": "tc_03"}, {"id": "tc_01"}, {"id": "tc_02"}]
    assert [c["id"] for c in filter_cases(cases, ("tc_02", "tc_01"))] == ["tc_01", "tc_02"]


def test_empty_filter_is_identity():
    cases = [{"id": "tc_01"}]
    assert filter_cases(cases, ()) == cases


def test_unmatched_ids_detects_bad_filter():
    cases = [{"id": "tc_01"}]
    assert unmatched_ids(cases, ("tc_99", "tc_01")) == ["tc_99"]
    assert unmatched_ids(cases, ()) == []


# --------------------------------------------------------------------------
# The real suites, against the real fixture registry
# --------------------------------------------------------------------------


def test_every_declared_fixture_in_the_repo_resolves(repo_root):
    """The whole point of declaring fixtures: they must be provisionable.

    A dangling declaration would show up as a missing_input failure at
    evaluation time and corrupt the metrics.
    """
    from pathlib import Path

    fixtures = Path("benchmarks/fixtures")
    if not fixtures.is_dir():
        pytest.skip("fixture registry not present")
    cases = []
    for suite in ("benchmark_prompts_tier1.json", "benchmark_prompts_tier2.json"):
        path = Path("benchmarks") / suite
        if path.is_file():
            cases += load_suite(path)
    unresolved = [
        (case_id, name)
        for case_id, name in required_fixtures(cases)
        if not resolve_fixture(fixtures, name)
    ]
    assert unresolved == []