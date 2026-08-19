"""Tests for src/workflow/builder.py — DAG structural correctness."""

import os

import pytest

os.environ.setdefault("MODEL_PROVIDER", "ollama")

from src.workflow.builder import build_tasks  # noqa: E402

SAMPLE_ARGS = dict(
    company_name="Acme Corp",
    known_challenges="Legacy systems",
    stakeholders="Jane (CTO)",
    raw_meeting_notes="Discussed migration timeline.",
)


@pytest.fixture
def tasks():
    return build_tasks(**SAMPLE_ARGS)


def test_five_tasks_generated(tasks):
    assert len(tasks) == 5


def test_all_task_ids_unique(tasks):
    ids = [t["task_id"] for t in tasks]
    assert len(ids) == len(set(ids))


def test_expected_task_ids_present(tasks):
    ids = {t["task_id"] for t in tasks}
    assert ids == {
        "company_research",
        "stakeholder_mapping",
        "meeting_summary",
        "discovery_questions",
        "follow_up_actions",
    }


def test_dependencies_reference_existing_tasks(tasks):
    ids = {t["task_id"] for t in tasks}
    for task in tasks:
        for dep in task.get("dependencies", []):
            assert dep in ids, f"{task['task_id']} depends on unknown task '{dep}'"


def test_no_cycles(tasks):
    """Simple DFS cycle check over the dependency graph."""
    graph = {t["task_id"]: t.get("dependencies", []) for t in tasks}
    visiting, visited = set(), set()

    def visit(node):
        if node in visited:
            return
        if node in visiting:
            pytest.fail(f"Cycle detected at '{node}'")
        visiting.add(node)
        for dep in graph[node]:
            visit(dep)
        visiting.discard(node)
        visited.add(node)

    for node in graph:
        visit(node)


def test_phase1_tasks_have_no_dependencies(tasks):
    """company_research, stakeholder_mapping and meeting_summary must be
    independent so they can run in parallel — this is the core of the
    Workflow pattern being demonstrated."""
    by_id = {t["task_id"]: t for t in tasks}
    for task_id in ["company_research", "stakeholder_mapping", "meeting_summary"]:
        assert by_id[task_id].get("dependencies", []) == []


def test_join_point_1_depends_on_both_parallel_branches(tasks):
    by_id = {t["task_id"]: t for t in tasks}
    assert set(by_id["discovery_questions"]["dependencies"]) == {
        "company_research",
        "stakeholder_mapping",
    }


def test_join_point_2_depends_on_both_upstream_outputs(tasks):
    by_id = {t["task_id"]: t for t in tasks}
    assert set(by_id["follow_up_actions"]["dependencies"]) == {
        "discovery_questions",
        "meeting_summary",
    }


def test_every_task_has_description_and_system_prompt(tasks):
    for task in tasks:
        assert task.get("description")
        assert task.get("system_prompt")


def test_every_task_shares_the_same_model_provider(tasks):
    """Design decision: a single provider for the whole run, not mixed
    per-task."""
    providers = {t["model_provider"] for t in tasks}
    assert len(providers) == 1


def test_every_task_has_no_tools(tasks):
    """Critical regression test — verified empirically: a task's own LLM,
    if given access to the `workflow` tool (which happens by default if
    no "tools" restriction is set — see NO_TOOLS in builder.py), can call
    it recursively and spin up a second, nested workflow with malformed
    tasks (no model_provider), which then crashes falling back to a
    default Bedrock model with no credentials. Every task must explicitly
    set "tools" to a placeholder that matches nothing in the tool registry,
    so it ends up with zero tools available."""
    for task in tasks:
        assert task.get("tools") == ["__no_tools__"]
