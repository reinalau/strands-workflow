"""
Assembles the final .md deliverable from a completed workflow run.

IMPORTANT (verified against strands_tools.workflow source):
Neither `action="start"` nor `action="status"` return the actual text
produced by each task — `start` returns only a success summary, and
`status` returns a Rich-formatted table. The real per-task output lives in
the workflow's persisted JSON file:

    ~/.strands/workflows/<workflow_id>.json
    -> task_results[task_id]["result"]  # list[{"text": ...}]

(path configurable via the STRANDS_WORKFLOW_DIR env var, same constant the
tool itself uses). This module reads that file directly.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional

WORKFLOW_DIR = Path(os.getenv("STRANDS_WORKFLOW_DIR", Path.home() / ".strands" / "workflows"))


def load_workflow_json(workflow_id: str) -> Dict:
    path = WORKFLOW_DIR / f"{workflow_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No persisted workflow found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_task_text(workflow_data: Dict, task_id: str) -> Optional[str]:
    """Extract the plain-text result of a single completed task."""
    task_result = workflow_data.get("task_results", {}).get(task_id, {})
    if task_result.get("status") != "completed":
        return None
    result = task_result.get("result") or []
    return "\n".join(item.get("text", "") for item in result if isinstance(item, dict))


def build_markdown_report(workflow_id: str) -> str:
    """Build the full educational .md report: shows every intermediate
    task output (so readers can see the Workflow's join points and context 
    passing working) plus the final follow_up_actions deliverable."""
    data = load_workflow_json(workflow_id)

    sections = [
        f"# Discovery Meeting Report — {workflow_id}",
        f"_Workflow status: {data.get('status')}_",
        "",
        "## Phase 1 (parallel) — Company Research",
        extract_task_text(data, "company_research") or "_(not available)_",
        "",
        "## Phase 1 (parallel) — Stakeholder Mapping",
        extract_task_text(data, "stakeholder_mapping") or "_(not available)_",
        "",
        "## Phase 1 (parallel) — Meeting Summary",
        extract_task_text(data, "meeting_summary") or "_(not available)_",
        "",
        "## Join Point #1 — Discovery Questions",
        extract_task_text(data, "discovery_questions") or "_(not available)_",
        "",
        "## Join Point #2 — Follow-up Deliverable",
        extract_task_text(data, "follow_up_actions") or "_(not available)_",
    ]
    return "\n\n".join(sections)
