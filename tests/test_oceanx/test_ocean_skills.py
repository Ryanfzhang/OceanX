"""Capability-gated packaged Ocean research skill tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from oceanx.skills import (
    LITERATURE_CAPABILITY,
    OceanResourceUnavailableError,
    load_ocean_skill,
    ocean_reference_root,
    ocean_skill_dirs,
    ocean_skill_metadata,
    ocean_skill_prompt_section,
)
from oceanx.tools import (
    OceanToolServices,
    create_ocean_expert_tool_registry,
    create_ocean_lead_tool_registry,
)


def test_core_ocean_skills_are_loaded_through_extra_skill_dirs_only():
    names = {skill.name for skill in ocean_skill_metadata()}

    assert {
        "ocean-dataset-diagnosis",
        "ocean-analysis-design",
        "hypothesis-experiment-design",
        "ocean-physical-consistency-review",
        "claim-grounded-writing",
        "reproducibility-audit",
        "research-trajectory-planning",
        "ocean-data-acquisition",
        "scientific-figure-design",
    } <= names
    assert "ocean-map-and-figure-review" not in names
    assert "paper-evidence-review" not in names
    content, _metadata = load_ocean_skill("ocean-analysis-design")
    assert "compute_" not in content


@pytest.mark.parametrize("role", ["ocean_process_expert", "statistical_inference_expert"])
def test_scientific_figure_skill_exposes_shared_palette_semantics(role):
    content, metadata = load_ocean_skill("scientific-figure-design", role=role)

    assert role in metadata.roles
    assert "ocean_teal" in content
    assert "blue_red" in content
    assert "grouped" in content


def test_literature_skill_remains_hidden_until_its_capability_is_enabled():
    default = {item.name for item in ocean_skill_metadata()}
    enabled = {item.name for item in ocean_skill_metadata(capabilities={LITERATURE_CAPABILITY})}

    assert "paper-evidence-review" not in default
    assert "paper-evidence-review" in enabled
    assert "paper-navigator" not in default
    assert "paper-navigator" in enabled
    assert len(ocean_skill_dirs()) == 1
    assert len(ocean_skill_dirs(capabilities={LITERATURE_CAPABILITY})) == 2


def test_acquisition_skills_use_existing_role_catalog_and_execution_tool():
    role = "literature_reproduction_expert"
    content, metadata = load_ocean_skill("ocean-data-acquisition", role=role)
    assert metadata.roles == (role,)
    assert "user-run" in content
    assert "ocean_expert_run_code" not in content
    assert "ocean_remote_data" not in content
    with pytest.raises(OceanResourceUnavailableError):
        load_ocean_skill("ocean-data-acquisition", role="coordinator")
    registry = create_ocean_expert_tool_registry(OceanToolServices(
        workspace_id="ws_download_skills", provider_id="provider_fixture",
        store=SimpleNamespace(), skill_role=role,
        expert_code_execution=SimpleNamespace(),
    ))
    names = {tool.name for tool in registry.list_tools()}
    assert "ocean_expert_run_code" in names
    assert "ocean_remote_data" not in names


def test_literature_expert_owns_paper_selection_before_report_delivery():
    async def select_papers(_payload, _context):
        return {"selected_paper_ids": ["paper-1"]}

    registry = create_ocean_expert_tool_registry(OceanToolServices(
        workspace_id="ws_paper_selection", provider_id="provider_fixture",
        store=SimpleNamespace(), skill_role="literature_reproduction_expert",
        skill_capabilities=(LITERATURE_CAPABILITY,),
        paper_selection_sink=select_papers,
    ))

    assert "ocean_request_paper_selection" in {tool.name for tool in registry.list_tools()}


def test_coordinator_cannot_request_paper_selection_even_if_a_sink_is_supplied():
    async def select_papers(_payload, _context):
        return {"selected_paper_ids": ["paper-1"]}

    registry = create_ocean_lead_tool_registry(OceanToolServices(
        workspace_id="ws_coordinator_paper_selection",
        provider_id="provider_fixture",
        store=SimpleNamespace(),
        skill_role="coordinator",
        paper_selection_sink=select_papers,
    ))

    assert "ocean_request_paper_selection" not in {tool.name for tool in registry.list_tools()}


def test_packaged_references_are_available_on_demand_without_entering_skill_metadata():
    references = ocean_reference_root()

    assert (references / "data" / "cf-conventions.md").is_file()
    assert (references / "methods" / "transport.md").is_file()
    assert (references / "coding" / "matplotlib.md").is_file()
    assert all("references/" not in item.description for item in ocean_skill_metadata())


def test_skill_prompt_is_metadata_only_and_respects_the_literature_gate():
    prompt = ocean_skill_prompt_section(role="ocean_process_expert")
    enabled_prompt = ocean_skill_prompt_section(
        capabilities={LITERATURE_CAPABILITY},
        role="literature_reproduction_expert",
    )

    assert "ocean-physical-consistency-review" in prompt
    assert "ocean-analysis-design" not in prompt
    assert "questions_to_resolve" not in prompt
    assert "paper-evidence-review" not in prompt
    assert "paper-evidence-review" in enabled_prompt
    assert "paper-navigator" not in prompt
    assert "paper-navigator" in enabled_prompt


def test_every_packaged_skill_declares_roles_and_role_gate_controls_loading():
    metadata = ocean_skill_metadata(capabilities={LITERATURE_CAPABILITY})

    assert all(item.roles for item in metadata)
    literature_names = {
        item.name
        for item in ocean_skill_metadata(
            capabilities={LITERATURE_CAPABILITY},
            role="literature_reproduction_expert",
        )
    }
    assert {"paper-navigator", "paper-evidence-review", "reproducibility-audit"} <= literature_names
    assert "ocean-dataset-diagnosis" not in literature_names

    content, _metadata = load_ocean_skill(
        "paper-evidence-review",
        capabilities={LITERATURE_CAPABILITY},
        role="literature_reproduction_expert",
    )
    assert "Choose reading depth from the question" in content
    with pytest.raises(OceanResourceUnavailableError):
        load_ocean_skill(
            "paper-evidence-review",
            capabilities={LITERATURE_CAPABILITY},
            role="ocean_process_expert",
        )
