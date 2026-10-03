"""Prompt regression checks protect a small contract, not historical wording."""
from types import SimpleNamespace

from oceanx.runtime import (
    OCEAN_AGENT_SKILL_POLICY,
    OCEAN_CHILD_BASE_SYSTEM_PROMPT,
    OCEAN_EXPERT_WORKSTREAM_POLICY,
    OCEAN_EXPLORATION_POLICY,
    OCEAN_RESEARCH_PARTNER_SYSTEM_PROMPT,
    build_ocean_runtime_composition,
)
from oceanx.deep_runtime import NATIVE_TASK_DESCRIPTION
from oceanx.team.models import ChildAuthority
from oceanx.team.profiles import AGENT_PROFILES, profile_system_prompt
from oceanx.tools import OceanToolServices


def _flatten(prompt: str) -> str:
    return " ".join(prompt.split())


def coordinator_prompt():
    services = OceanToolServices(workspace_id="ws", provider_id="fixture", store=SimpleNamespace(),
        task_id="task", skill_role="coordinator", coordinator_enabled=True)
    composition = build_ocean_runtime_composition(services)
    return _flatten(OCEAN_RESEARCH_PARTNER_SYSTEM_PROMPT + "\n" +
                    "\n".join(composition.profile.system_prompt_sections))


def test_experts_report_missing_data_without_acquiring_replacements():
    # One shared policy, rather than copies in every profile and method section.
    prompt = _flatten(OCEAN_CHILD_BASE_SYSTEM_PROMPT)
    assert "Do not acquire or re-acquire datasets" in prompt
    assert "user explicitly requests it" in prompt
    assert "Search Expert handles" in prompt
    assert "report missing evidence" in prompt
    assert "Do not access unrelated files or credentials" in prompt


def test_coordinator_keeps_user_constraints_and_publication_contract():
    prompt = coordinator_prompt()
    assert "Sources are read-only" in prompt
    assert "Only an explicit user request authorizes dataset acquisition" in prompt
    assert "Naming an external dataset as necessary comparison evidence" in prompt
    assert "Literature acquisition mode governs paper full text" in prompt
    assert "Agent-qualified key" in prompt
    assert "Never invent result1" in prompt  # graphs.py adds the run's concrete key example
    assert "ocean_publish_outputs" not in prompt
    assert "user's scientific question in its language" in prompt


def test_coordinator_is_short_and_delegates_questions_not_method_forms():
    prompt = coordinator_prompt()
    assert len(prompt) < 5_000
    assert "Literature expands and tests the initial problem space" in prompt
    assert "it never determines the tree by itself" in prompt
    assert "Select a scientific subquestion before choosing expertise" in prompt
    assert "the Expert chooses methods" in prompt
    assert "Independent questions may run in parallel" in prompt
    assert "Search Expert pauses its own native task" in prompt
    assert "Do not request papers after it has delivered" in prompt
    assert "Never turn the assignment into a method, metric, figure" in prompt
    assert "opens an independent root direction" in prompt
    assert "Optional experience capture" not in prompt
    assert "# Optional method guidance" not in prompt
    assert "# OceanX Hierarchical Professional Team" not in prompt
    assert "# Handoff" not in prompt


def test_simple_requests_and_user_methods_do_not_become_research_workflows():
    prompt = coordinator_prompt()
    assert "Simple requested operations skip it and do not become research trees" in prompt


def test_standard_mode_keeps_team_policy_but_removes_tree_policy():
    services = OceanToolServices(workspace_id="ws", provider_id="fixture", store=SimpleNamespace(),
        task_id="task", skill_role="coordinator", coordinator_enabled=True)
    composition = build_ocean_runtime_composition(services, research_mode=False)
    prompt = _flatten("\n".join(composition.profile.system_prompt_sections))

    assert "# Research tree" not in prompt
    assert "# Research coordination" not in prompt
    assert "# Coordinator" in prompt
    assert "Delegate data analysis" in prompt
    assert "Search Expert acquires a named public comparison dataset" in prompt


def test_experts_keep_evidence_without_workflow_checklists():
    for profile in AGENT_PROFILES:
        if profile.authority is ChildAuthority.EXPERT:
            prompt = _flatten(profile_system_prompt(profile))
            assert "Answer only the assigned subquestion" in prompt
            assert "supporting inspection, analysis, statistics and figures" in prompt
            assert "not method checklists or boundaries" in prompt
            assert "Separate direct evidence from interpretation" in prompt
            assert "evidence-limited answer is complete" in prompt
            assert "For a specified non-research output, produce that output" in prompt
    policy = _flatten(OCEAN_EXPERT_WORKSTREAM_POLICY)
    assert "Keep verified calculations and code" in policy
    assert "Derive reported values and labels from saved calculations" in policy
    assert "Do not spend a separate round polishing" in policy
    # Most failed code runs across tasks were shape/axis mistakes after dropping to bare arrays.
    assert "select and reduce by dimension name" in policy and "not as bare .npz" in policy


def test_data_work_does_not_wait_for_the_literature_consultation():
    prompt = coordinator_prompt()
    assert "Start with questions the supplied data can answer" in prompt
    assert ("Consult the Search Expert only when the question turns on a definition, method or "
            "published mechanism DatasetContext does not settle, alongside the data questions, "
            "not before them") in prompt
    # The consultation is the Coordinator's choice, not a preset first step.
    assert "Launch the bounded literature consultation" not in prompt
    assert "one bounded standalone" not in prompt
    assert "Before delegating, use the data context and bounded literature" not in prompt


def test_a_consultation_reads_sources_and_does_not_analyse_the_task_data():
    from oceanx.team.profiles import get_agent_profile

    search = _flatten(profile_system_prompt(get_agent_profile("literature_reproduction_expert")))
    assert "A consultation reads sources and reports; it does not analyse the task's data" in search
    assert ("When sources conflict, or only a numerical check can decide, say so and stop: the "
            "Coordinator assigns the check to a data Expert") in search
    assert ("Run code only when the assignment explicitly asks to reproduce a result or download "
            "data") in search
    for role in ("ocean_process_expert", "statistical_inference_expert"):
        assert "A consultation reads sources" not in _flatten(
            profile_system_prompt(get_agent_profile(role)))


def test_delivery_uses_assigned_file_not_a_terminal_tool():
    prompt = _flatten(OCEAN_CHILD_BASE_SYSTEM_PROMPT + OCEAN_EXPERT_WORKSTREAM_POLICY)
    assert "backend-assigned report file" in prompt
    assert "Finish normally after saving" in prompt
    assert "ocean_deliver" not in prompt
    assert "finish by calling it alone" not in prompt


def test_expert_summary_exposes_an_unresolved_direction_without_a_second_contract():
    prompt = _flatten(OCEAN_CHILD_BASE_SYSTEM_PROMPT)
    assert "Result, Evidence and limitations, and Further analysis" in prompt
    assert "says None" in prompt


def test_notes_and_skills_are_not_hidden_coordination_protocols():
    assert "branches are scientific subquestions" in OCEAN_EXPLORATION_POLICY
    assert "report.md's" in OCEAN_EXPLORATION_POLICY
    assert "not a checklist" in OCEAN_EXPLORATION_POLICY
    assert "scientific methods, never delegation" in OCEAN_AGENT_SKILL_POLICY
    assert "Optional method guidance" in OCEAN_AGENT_SKILL_POLICY
    assert "read_file" in OCEAN_AGENT_SKILL_POLICY
    assert "one scientific question" in NATIVE_TASK_DESCRIPTION
    assert "Parent question, Parent answer, Parent report" in NATIVE_TASK_DESCRIPTION
    assert "Do not prescribe methods, metrics, figures" in NATIVE_TASK_DESCRIPTION


def test_experts_label_what_they_save_so_a_later_step_need_not_open_it():
    from oceanx.runtime import STATIC_EXPERT_WORKSTREAM_POLICY

    for policy in (OCEAN_EXPERT_WORKSTREAM_POLICY, STATIC_EXPERT_WORKSTREAM_POLICY):
        assert ("Give every variable you save `units` and `long_name` attributes and the file a "
                "one-line `title` attribute") in _flatten(policy)
        assert "requested a visual or" in _flatten(policy)
