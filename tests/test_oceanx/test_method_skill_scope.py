"""Method Skills must not reintroduce the removed orchestration playbook."""

import pytest

from oceanx.skills import load_ocean_skill, ocean_skill_metadata, validate_ocean_skill_document


@pytest.mark.parametrize("role", [
    "coordinator", "ocean_process_expert", "statistical_inference_expert",
    "literature_reproduction_expert",
    "scientific_discussion_partner",
])
def test_consolidated_skills_are_not_separate_native_entries(tmp_path, role):
    from oceanx.native_skills import prepare_skill_library

    library = prepare_skill_library(tmp_path / role, role=role)
    names = {s.name for s in ocean_skill_metadata(role=role)}
    for name in ("ocean-question-and-scale-framing", "paper-grounded-idea-framing",
                 "cmems-data-acquisition", "modis-ocean-download", "seawifs-ocean-download"):
        assert name not in names
        assert not (library / "skills" / name).exists()


@pytest.mark.parametrize("name", [
    "research-trajectory-planning", "ocean-analysis-design", "claim-grounded-writing",
    "ocean-physical-consistency-review", "scientific-figure-design", "paper-navigator",
])
def test_methods_keep_discoverable_headers_without_coordination_protocols(name):
    content, skill = load_ocean_skill(name, capabilities=("literature.read",))
    assert skill.name == name
    assert skill.description
    assert "metadata:" in content and "roles:" in content
    for removed in ("ocean_assign", "two review rounds", "hypothesis states",
                    "subsequent Statistical Expert assignment", "current task's ResultBundle",
                    "do not restart discovery as another instance", "Coordinator should\nrevise"):
        assert removed not in content


def test_numeric_method_examples_remain_available_on_demand():
    analysis, _ = load_ocean_skill("ocean-analysis-design")
    physical, _ = load_ocean_skill("ocean-physical-consistency-review")
    from oceanx.skill_regions import packaged_skill
    from oceanx.skills import ocean_skill_dirs
    array = packaged_skill(ocean_skill_dirs()[0] / "xarray-array-ops", load_ocean_skill("xarray-array-ops")[0])
    assert "/skills/xarray-array-ops/SKILL.md" in analysis
    # The function list is written from the code, so every helper is described where it is read.
    for name in ("check_dims", "exact_align", "column_take", "masked_values", "small_sample",
                 "weighted_mean", "rate_per_day", "angular_gradient_per_metre"):
        assert f"- `ao.{name}(" in array
    assert "oceanx:" not in array
    assert "numerator and denominator" in analysis
    assert "rho * cp * H * tendency_K_per_day / 86400" in physical
    assert "residual" in physical


@pytest.mark.parametrize("name,owner", [
    ("ocean-physical-consistency-review", "ocean_process_expert"),
    ("ocean-analysis-design", "statistical_inference_expert"),
    ("ocean-data-acquisition", "literature_reproduction_expert"),
])
@pytest.mark.parametrize("role", [
    "coordinator", "ocean_process_expert", "scientific_discussion_partner",
    "statistical_inference_expert", "literature_reproduction_expert",
])
def test_domain_method_native_libraries_are_role_scoped(tmp_path, name, owner, role):
    from oceanx.native_skills import prepare_skill_library
    from oceanx.skills import OceanResourceUnavailableError

    available = role == owner
    library = prepare_skill_library(tmp_path / role, role=role)
    assert (library / "skills" / name / "SKILL.md").is_file() is available
    if available:
        _, metadata = load_ocean_skill(name, role=role)
        assert role in metadata.roles
    else:
        with pytest.raises(OceanResourceUnavailableError):
            load_ocean_skill(name, role=role)


def test_download_provider_references_follow_the_literature_library(tmp_path):
    from oceanx.native_skills import prepare_skill_library

    library = prepare_skill_library(tmp_path / "literature", role="literature_reproduction_expert")
    guide = library / "skills/ocean-data-acquisition"
    entry = (guide / "SKILL.md").read_text()
    for provider in ("cmems", "modis", "seawifs"):
        path = f"references/{provider}.md"
        assert (guide / path).is_file()
        assert f"/skills/ocean-data-acquisition/{path}" in entry
        assert not (guide / path).read_text().startswith("---")


def test_heat_budget_is_content_not_a_separate_skill():
    assert "ocean-heat-budget" not in {s.name for s in ocean_skill_metadata()}
    for skill in ocean_skill_metadata():
        content, _ = load_ocean_skill(skill.name)
        assert "/skills/ocean-heat-budget/" not in content


def test_all_packaged_skills_keep_routing_headers_and_drop_retired_artifact_contracts():
    for item in ocean_skill_metadata(capabilities=("literature.read",)):
        content, _ = load_ocean_skill(item.name, capabilities=("literature.read",))
        metadata = validate_ocean_skill_document(content, expected_name=item.name)
        assert metadata.roles == item.roles
        for obsolete in ("DatasetDiagnosisArtifact", "HypothesisArtifact", "DecisionArtifact",
                         "expert_key", "todo_id", "legacy work graph"):
            assert obsolete not in content, (item.name, obsolete)
