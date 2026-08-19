"""
Deterministic metrics for the Workflow pattern evaluation.

These measure properties of the workflow's execution and output structure
that have no equivalent in the strands-agents-evals SDK, because they are
specific to the Workflow orchestration pattern:

- task_completion_rate  : fraction of tasks that reached status="completed"
                          in the persisted workflow JSON (topology metric).
- join_point_coverage   : whether both join points (discovery_questions,
                          follow_up_actions) have non-empty outputs.
- required_sections     : deterministic check that follow_up_actions produced
                          all three required deliverable sections.
- stakeholder_coverage  : whether each expected stakeholder is mentioned in
                          the discovery_questions output.
- keyword_presence      : whether domain-specific keywords appear in a given
                          task output (regression check for prompt drift).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Task Completion ────────────────────────────────────────────────────────────

@dataclass
class TaskCompletionResult:
    total_tasks: int
    completed_tasks: int
    failed_tasks: List[str]
    rate: float  # completed / total


def compute_task_completion(workflow_data: Dict) -> TaskCompletionResult:
    """Check how many tasks completed successfully in the persisted workflow JSON.

    A task that ended with status != 'completed' blocks its dependents and
    can hang the workflow (verified limitation in README). This metric surfaces
    that structural failure clearly.

    Args:
        workflow_data: The raw dict loaded from <workflow_id>.json.

    Returns:
        TaskCompletionResult with counts and the list of failed task IDs.
    """
    task_results = workflow_data.get("task_results", {})
    completed = [tid for tid, r in task_results.items() if r.get("status") == "completed"]
    failed = [tid for tid, r in task_results.items() if r.get("status") != "completed"]
    total = len(task_results)
    rate = len(completed) / total if total > 0 else 0.0
    return TaskCompletionResult(
        total_tasks=total,
        completed_tasks=len(completed),
        failed_tasks=failed,
        rate=rate,
    )


# ── Join Point Coverage ────────────────────────────────────────────────────────

JOIN_POINT_TASK_IDS = ["discovery_questions", "follow_up_actions"]


@dataclass
class JoinPointCoverageResult:
    discovery_questions_ok: bool
    follow_up_actions_ok: bool
    all_ok: bool


def compute_join_point_coverage(task_texts: Dict[str, Optional[str]]) -> JoinPointCoverageResult:
    """Verify that both join points produced non-empty output.

    The Workflow pattern's key structural property is that join points
    receive injected context from their dependencies. If a join point has
    no output, the dependency injection failed or the task errored out.

    Args:
        task_texts: Dict mapping task_id -> extracted plain text (or None).

    Returns:
        JoinPointCoverageResult with per-join-point and overall status.
    """
    dq_ok = bool(task_texts.get("discovery_questions", ""))
    fa_ok = bool(task_texts.get("follow_up_actions", ""))
    return JoinPointCoverageResult(
        discovery_questions_ok=dq_ok,
        follow_up_actions_ok=fa_ok,
        all_ok=dq_ok and fa_ok,
    )


# ── Required Sections in follow_up_actions ────────────────────────────────────

# The follow_up_actions system prompt explicitly requires these three sections.
# Any production deliverable missing one is incomplete regardless of quality.
REQUIRED_SECTIONS = ["follow-up email", "next steps", "gaps"]


@dataclass
class RequiredSectionsResult:
    present: List[str]
    missing: List[str]
    all_present: bool


def check_required_sections(
    follow_up_text: str,
    required: List[str] = REQUIRED_SECTIONS,
) -> RequiredSectionsResult:
    """Deterministically verify the three mandatory deliverable sections.

    Uses case-insensitive substring match — the LLM may vary exact headings
    (e.g. "Follow-Up Email Draft" vs "Follow-up email") but the key noun
    should always appear.

    Args:
        follow_up_text: Output of the follow_up_actions task.
        required: List of lowercase section keywords to search for.

    Returns:
        RequiredSectionsResult listing what was found and what was missing.
    """
    lowered = follow_up_text.lower()
    present = [s for s in required if s in lowered]
    missing = [s for s in required if s not in lowered]
    return RequiredSectionsResult(
        present=present,
        missing=missing,
        all_present=len(missing) == 0,
    )


# ── Stakeholder Coverage ───────────────────────────────────────────────────────

@dataclass
class StakeholderCoverageResult:
    expected: List[str]
    found: List[str]
    missing: List[str]
    coverage_rate: float  # found / expected


def check_stakeholder_coverage(
    discovery_questions_text: str,
    expected_stakeholders: List[str],
) -> StakeholderCoverageResult:
    """Check whether each stakeholder from the input appears in the discovery
    questions output.

    Matches any token of the stakeholder string (first name, last name, or
    full name) so "Maria Gomez" is found even if the model only wrote "Maria"
    or only "Gomez". Case-insensitive.

    Args:
        discovery_questions_text: Output of the discovery_questions task.
        expected_stakeholders: List of stakeholder name strings from the input.

    Returns:
        StakeholderCoverageResult with per-stakeholder presence and a rate.
    """
    lowered = discovery_questions_text.lower()

    def _stakeholder_present(name: str) -> bool:
        # Match any whitespace-separated token of the name
        return any(token.lower() in lowered for token in name.split())

    found = [s for s in expected_stakeholders if _stakeholder_present(s)]
    missing = [s for s in expected_stakeholders if not _stakeholder_present(s)]
    total = len(expected_stakeholders)
    return StakeholderCoverageResult(
        expected=expected_stakeholders,
        found=found,
        missing=missing,
        coverage_rate=len(found) / total if total > 0 else 0.0,
    )


# ── Keyword Presence ──────────────────────────────────────────────────────────

@dataclass
class KeywordPresenceResult:
    expected: List[str]
    found: List[str]
    missing: List[str]
    all_present: bool


def check_keyword_presence(
    text: str,
    keywords: List[str],
) -> KeywordPresenceResult:
    """Case-insensitive check that domain keywords — or any of their synonyms —
    appear in a task output.

    Each entry in `keywords` can be a single term or a pipe-separated list of
    synonyms (e.g. "migration|modernization|cloud adoption"). A keyword is
    considered present if ANY of its synonyms appears in the text.
    Used as a regression check: if the model completely ignores domain
    vocabulary from the input, the prompt or context injection is broken.

    Args:
        text: Task output text to search in.
        keywords: List of keyword strings, each optionally containing
                  pipe-separated synonyms.

    Returns:
        KeywordPresenceResult with found/missing split and overall pass flag.
    """
    lowered = text.lower()

    def _any_synonym_present(keyword: str) -> bool:
        return any(syn.strip().lower() in lowered for syn in keyword.split("|"))

    found = [kw for kw in keywords if _any_synonym_present(kw)]
    missing = [kw for kw in keywords if not _any_synonym_present(kw)]
    return KeywordPresenceResult(
        expected=keywords,
        found=found,
        missing=missing,
        all_present=len(missing) == 0,
    )
