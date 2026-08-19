"""
Discovery Meeting Copilot — Workflow definition with Dependency Resolution.

Domain inspired by Jeff Scott's PartyRock app ("Prepare & Manage meeting as a
Solution Architect"), redesigned so tasks actually depend on each other's
outputs — which is what justifies using the Strands `workflow` orchestration
pattern instead of a flat set of independent single-shot prompts.

Task execution sequence (verified against dependencies, not just narrative "phases"):

    company_research ──────┐
                            ├──→ discovery_questions ──┐
    stakeholder_mapping ───┘                            ├──→ follow_up_actions
                                                          │
    meeting_summary ─────────────────────────────────────┘

`company_research`, `stakeholder_mapping` and `meeting_summary` have no
dependencies on each other, so all three run in parallel. `discovery_questions`
and `follow_up_actions` are the two join points — convergence points where 
parallel paths come together. This is why the Workflow Tool's automatic 
dependency resolution and context passing are justified.
"""

from typing import Dict, List

from src.agents.prompts import SYSTEM_PROMPTS
from src.config import get_model_config

# IMPORTANT (verified empirically): workflow.py's per-task tool filtering has
# a footgun — passing "tools": [] (empty list) does NOT restrict a task to
# zero tools. Because `if task_tools and ...` treats an empty list as falsy,
# it falls through to the `elif` branch and the task agent inherits ALL of
# the parent agent's tools instead, including the `workflow` tool itself.
# Observed consequence: a task's own LLM, seeing `workflow` available as a
# callable function, called it recursively — creating a second, nested
# workflow with tasks that had no model_provider set, which then fell back
# to Bedrock and crashed with "Unable to locate credentials".
# Workaround: pass a placeholder name that doesn't exist in the tool
# registry. No name matches, so filtered_tools stays empty (only a benign
# "Tool not found" warning is logged) — this is how you actually get a
# task agent with zero tools.
NO_TOOLS = ["__no_tools__"]


def build_tasks(
    company_name: str,
    known_challenges: str,
    stakeholders: str,
    raw_meeting_notes: str,
) -> List[Dict]:
    """Build the full task list for a single discovery-meeting run.

    Every task shares the same model_provider/model_settings (see
    src.config.get_model_config) — the point of this project is to
    demonstrate the Workflow orchestration pattern itself, not multi-provider
    routing.
    """
    model_cfg = get_model_config()

    return [
        # --- No dependencies: run in parallel ---
        {
            "task_id": "company_research",
            "description": f"Research this company for discovery prep: {company_name}",
            "system_prompt": SYSTEM_PROMPTS["company_research"],
            "priority": 4,
            "tools": NO_TOOLS,
            **model_cfg,
        },
        {
            "task_id": "stakeholder_mapping",
            "description": (
                f"Known challenges: {known_challenges}\n"
                f"Stakeholders: {stakeholders}\n"
                "Map each stakeholder to likely priorities and objections."
            ),
            "system_prompt": SYSTEM_PROMPTS["stakeholder_mapping"],
            "priority": 4,
            "tools": NO_TOOLS,
            **model_cfg,
        },
        {
            "task_id": "meeting_summary",
            "description": f"Summarize these raw meeting notes:\n{raw_meeting_notes}",
            "system_prompt": SYSTEM_PROMPTS["meeting_summary"],
            "priority": 3,
            "tools": NO_TOOLS,
            **model_cfg,
        },
        # --- Join point #1 ---
        {
            "task_id": "discovery_questions",
            "description": "Generate discovery questions informed by the research and stakeholder map above.",
            "dependencies": ["company_research", "stakeholder_mapping"],
            "system_prompt": SYSTEM_PROMPTS["discovery_questions"],
            "priority": 5,
            "tools": NO_TOOLS,
            **model_cfg,
        },
        # --- Join point #2: final deliverable ---
        {
            "task_id": "follow_up_actions",
            "description": (
                "Compare the planned discovery questions against what actually "
                "happened in the meeting summary, then produce the follow-up "
                "deliverable (email draft, next steps, gaps)."
            ),
            "dependencies": ["discovery_questions", "meeting_summary"],
            "system_prompt": SYSTEM_PROMPTS["follow_up_actions"],
            "priority": 5,
            "tools": NO_TOOLS,
            **model_cfg,
        },
    ]