"""Coordinator sees existing scientific facts without a new data-probing gate."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from oceanx.artifacts.models import ArtifactRef
from oceanx.context import ModelDataDisclosurePolicy, OceanContextBuilder
from oceanx.dataset_context import compact_dataset_context, source_metadata_summary


def artifact(name="dataset_local", version=1, **content):
    return SimpleNamespace(ref=ArtifactRef(artifact_id=name, version=version),
        artifact_type="dataset", title=name, summary="", content=content)


def cache_file(root, item):
    return root / (hashlib.sha256(item.ref.key.encode()).hexdigest()[:32] + ".json")


def cached_metadata(root, item):
    raw = {"inspection": "ready", "dimensions": {"time": 365, "depth": 50},
           "time_range": ["2011-01-01", "2011-12-31"],
           "coordinates": [{"name": "depth", "extent": [0, 5000], "attrs": {"units": "m"}}],
           "data_variables": [{"name": "temperature", "dims": ["time", "depth"],
               "attrs": {"units": "degC", "standard_name": "sea_water_temperature", "history": "PRIVATE_LOG"},
               "values": [987654321]}], "path": "/not/read/source.nc", "history": "PRIVATE_LOG"}
    cache_file(root, item).write_text(json.dumps({"sources": [raw]}))
    return raw


def builder(records, *, denied=False):
    store = SimpleNamespace(
        get_research_task=lambda task_id, **_: object() if task_id == "task_local" else None,
        workspace_snapshot=lambda _: SimpleNamespace(workspace_id="ws", revision=1),
        list_task_artifacts=lambda **_: records,
        get_projection=lambda **_: None,
        record_disclosure_audit=Mock(),
    )
    result = OceanContextBuilder(store=store)
    result.policy_for = lambda **_: ModelDataDisclosurePolicy(
        provider_id="fixture", policy_version=1, metadata="deny" if denied else "allow")
    return result


def test_coordinator_and_expert_use_same_cached_facts_without_raw_values(tmp_path):
    item = artifact()
    raw = cached_metadata(tmp_path, item)
    expert = compact_dataset_context({"sources": [raw]})["sources"][0]
    coordinator = source_metadata_summary(item, tmp_path)
    for key in ("dimensions", "coordinates", "data_variables", "time_range"):
        assert coordinator[key] == expert[key]
    assert "987654321" not in json.dumps(coordinator)
    assert "PRIVATE_LOG" not in json.dumps(coordinator)
    assert "path" not in coordinator


@pytest.mark.parametrize("bad_cache", ["absent", "corrupt", "too_large", "symlink", "old_version"])
def test_unavailable_cache_is_unknown_not_a_startup_failure(tmp_path, bad_cache):
    item = artifact(format="netcdf", variables=["salinity"])
    path = cache_file(tmp_path, item)
    if bad_cache == "corrupt":
        path.write_text("not json")
    elif bad_cache == "too_large":
        path.write_text(" " * 2_000_001)
    elif bad_cache == "symlink":
        other = tmp_path / "other.json"
        other.write_text(json.dumps({"sources": [{"inspection": "ready"}]}))
        path.symlink_to(other)
    elif bad_cache == "old_version":
        cached_metadata(tmp_path, artifact(version=2))
    result = source_metadata_summary(item, tmp_path)
    assert result["inspection"] == "registered_only"
    assert result["variables"] == ["salinity"]


def test_context_scopes_sources_handles_and_disclosure_before_cache_read(tmp_path, monkeypatch):
    item = artifact()
    cached_metadata(tmp_path, item)
    # A paper consumes source_1 just as in the actual delegation source resolver.
    paper = SimpleNamespace(**{**item.__dict__, "artifact_type": "paper", "ref": ArtifactRef(artifact_id="paper_local", version=1)})
    records = [SimpleNamespace(artifact=paper, relations=("source",)),
               SimpleNamespace(artifact=item, relations=("source",))]
    local = builder(records)
    result = local.build(workspace_id="ws", provider_id="fixture", task_id="task_local",
                         routing_only=True, dataset_context_root=tmp_path)
    assert result.payload["dataset_context"]["sources"][0]["handle"] == "source_2"
    assert result.payload["dataset_context"]["sources"][0]["data_variables"][0]["units"] == "degC"
    assert result.estimated_tokens <= 3000
    local.store.record_disclosure_audit.assert_called_once()
    monkeypatch.setattr("oceanx.context.source_metadata_summary", lambda *_: pytest.fail("Disclosure denied: must not read cache"))
    denied = builder(records, denied=True).build(workspace_id="ws", provider_id="fixture",
        task_id="task_local", routing_only=True, dataset_context_root=tmp_path)
    assert "dataset_context" not in denied.payload


def test_source_metadata_obeys_context_budget_without_truncated_json(tmp_path):
    item = artifact(variables=["temperature_" + "x" * 2000] * 100)
    result = builder([SimpleNamespace(artifact=item, relations=("source",))]).build(
        workspace_id="ws", provider_id="fixture", task_id="task_local", routing_only=True,
        dataset_context_root=tmp_path, token_budget=400)
    assert result.estimated_tokens <= 400
    source = result.payload["dataset_context"]["sources"][0]
    assert source["metadata_omitted"] is True
    assert source["ref"] == item.ref.model_dump(mode="json")
