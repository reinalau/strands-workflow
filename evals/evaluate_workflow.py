"""
Evaluation runner for the Discovery Meeting Copilot workflow.

Uses strands-agents-evals to evaluate the workflow's output quality, combining:
  - OutputEvaluator      : LLM-as-a-judge scoring the follow_up_actions deliverable
                           against a rubric (format correctness + business utility).
  - HelpfulnessEvaluator : Seven-level helpfulness score assessing whether the
                           output is genuinely useful for a Solutions Architect.
  - Deterministic metrics: task completion rate, join point coverage, required
                           sections check, stakeholder coverage, keyword presence.
                           Computed outside the SDK — they measure workflow-level
                           structural properties, not output quality.

The two LLM-as-judge evaluators use the same model provider configured in
src/config.py (Gemini or Ollama), not Amazon Bedrock — consistent with the
project's local-first design.

IMPORTANT — two-phase structure (fixes a real crash, not cosmetic):
  Phase 1 (run_all_workflows_sync): runs every eval case's full workflow,
      100% synchronously, with NO asyncio event loop active anywhere.
  Phase 2 (run_judge_evaluations_async, inside asyncio.run()): only does
      LLM-as-judge scoring against the already-computed text from Phase 1.
Verified empirically that mixing them (running the workflow inside
asyncio.to_thread() under an outer asyncio.run(), as an earlier version of
this script did) crashes intermittently with "Connector is closed" /
"attached to a different loop" — LiteLLM caches its async HTTP client at
module level, bound to whichever event loop first used it; nested/competing
loops break that cached client. Keeping Phase 1 fully sync avoids the issue.

Usage:
    python -m evals.evaluate_workflow

Output:
    - Console: per-case scores, deterministic metrics, global summary.
    - outputs/eval_report_<timestamp>.json: full structured report.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

# MUST be set before any strands_tools import — workflow.py reads this env var
# when creating its ThreadPoolExecutor. Setting it here (module level, before
# the strands_tools import below) forces sequential task execution in the eval
# runner, preventing the aiohttp "attached to a different loop" race condition
# that occurs when multiple threads each call asyncio.run() and LiteLLM's
# module-level cached async HTTP client ends up bound to different event loops.
# Trade-off: eval runs are slower (tasks run one at a time); src/main.py runs
# are unaffected because they don't set this variable.
os.environ.setdefault("STRANDS_WORKFLOW_MAX_THREADS", "1")

from dotenv import load_dotenv

load_dotenv()  # must run before importing src.config

from strands import Agent
from strands_evals import Case, Experiment
from strands_evals.evaluators import OutputEvaluator
from strands_tools import workflow

from src.config import MODEL_PROVIDER, get_model_config
from src.models.schemas import DiscoveryMeetingInput
from src.utils.report_export import OUTPUTS_DIR
from src.workflow.builder import build_tasks
from src.workflow.deliverable import extract_task_text, load_workflow_json
from src.workflow.instrumentation import install_task_timing_hooks

from evals.metrics import (
    check_keyword_presence,
    check_required_sections,
    check_stakeholder_coverage,
    compute_join_point_coverage,
    compute_task_completion,
)

TEST_CASES_PATH = Path(__file__).parent / "test_cases" / "workflow_eval_cases.json"
REPORT_FILENAME_PREFIX = "eval_report"

# ── Rubric for the LLM-as-a-judge ─────────────────────────────────────────────

_FOLLOW_UP_RUBRIC = """
You are evaluating the output of a multi-agent workflow that helps a Solutions
Architect close a discovery meeting. The output should be a professional
follow-up deliverable with three clearly identifiable sections:
  1. A follow-up email draft addressed to the meeting participants.
  2. Concrete next steps with owners or responsible parties.
  3. Gaps — questions that were planned but never addressed in the meeting.

Score 1.0 — All three sections are present and clearly distinct; the email is
            professional and addresses the actual meeting content; next steps
            are specific (not generic); gaps are grounded in what was planned
            vs. what actually happened.
Score 0.5 — Two of the three sections are present, or all three are present but
            the content is generic / not grounded in the meeting specifics.
Score 0.0 — Only one section or none; the output is off-topic, a refusal, or
            does not resemble a professional SA deliverable.
"""

# HelpfulnessEvaluator from strands-agents-evals requires an OpenTelemetry
# Session trace object as actual_trajectory — incompatible with the workflow
# tool which does not expose a Strands Session. Replaced with a second
# OutputEvaluator using a helpfulness-focused rubric (same workaround used
# in strands-graph for CorrectnessEvaluator).
_HELPFULNESS_RUBRIC = """
You are evaluating whether the output of a Solutions Architect assistant is
genuinely helpful to a professional preparing for or closing a discovery meeting.

Consider:
  1. Actionability — are next steps concrete and assigned to specific owners?
  2. Relevance — is the content grounded in the actual meeting context provided,
     not generic boilerplate?
  3. Completeness — does it address the key concerns raised by each stakeholder?
  4. Professional tone — is the email draft ready to send with minimal edits?

Score 1.0 — Highly useful: a real SA could use this output with minimal edits.
Score 0.5 — Partially useful: some sections are actionable but others are generic
            or miss important stakeholder concerns.
Score 0.0 — Not useful: generic, off-topic, or would require full rewrite.
"""


def _load_cases() -> list[dict]:
    with TEST_CASES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _build_workflow_id(case_id: str) -> str:
    """Generate a deterministic, short workflow ID for an eval case."""
    return f"eval_{case_id}"


def _run_workflow_and_collect_sync(raw_case: dict) -> tuple[str, dict]:
    """Run the full workflow for one eval case and return the follow_up_actions
    text plus a dict of all task texts for deterministic metrics.

    IMPORTANT (verified empirically): this MUST run with no asyncio event
    loop active anywhere above it in the call stack. LiteLLM caches its async
    HTTP client at module level (litellm.module_level_aclient), bound to
    whichever event loop first used it. Wrapping this in asyncio.to_thread()
    under an outer asyncio.run() (as an earlier version of this file did)
    creates nested/competing event loops — the cached client ends up attached
    to a loop that later gets torn down, causing intermittent crashes:
    "Connector is closed" / "attached to a different loop". Running this
    fully synchronously, BEFORE any asyncio.run() context exists (see
    run_all_workflows_sync below), avoids the issue entirely.
    """
    install_task_timing_hooks()  # visibility: prints START/END per task,
    # otherwise this runs 5 real LLM calls with zero console output until
    # fully done — easy to mistake for a hang.
    meeting_input = DiscoveryMeetingInput(**raw_case["input"])
    workflow_id = _build_workflow_id(raw_case["id"])

    tasks = build_tasks(
        company_name=meeting_input.company_name,
        known_challenges=meeting_input.known_challenges,
        stakeholders=meeting_input.stakeholders,
        raw_meeting_notes=meeting_input.raw_meeting_notes,
    )

    agent = Agent(tools=[workflow])
    create_result = agent.tool.workflow(
        action="create", workflow_id=workflow_id, tasks=tasks
    )
    if create_result.get("status") != "success":
        raise RuntimeError(f"Workflow create failed: {create_result}")

    agent.tool.workflow(action="start", workflow_id=workflow_id)

    # Read results from persisted JSON
    wf_data = load_workflow_json(workflow_id)
    task_ids = ["company_research", "stakeholder_mapping", "meeting_summary",
                "discovery_questions", "follow_up_actions"]
    task_texts = {tid: extract_task_text(wf_data, tid) or "" for tid in task_ids}

    # Cleanup — delete persisted workflow after reading
    agent.tool.workflow(action="delete", workflow_id=workflow_id)

    follow_up_text = task_texts.get("follow_up_actions", "")
    return follow_up_text, {"wf_data": wf_data, "task_texts": task_texts}


def _compute_side_metrics(raw: dict, follow_up_text: str, wf_data: dict, task_texts: dict) -> dict:
    """Deterministic, non-LLM metrics for a single case (see evals/metrics.py)."""
    completion = compute_task_completion(wf_data)
    join_points = compute_join_point_coverage(task_texts)
    sections = check_required_sections(follow_up_text)
    stakeholders = check_stakeholder_coverage(
        task_texts.get("discovery_questions", ""),
        raw.get("expected_stakeholders", []),
    )
    kw_research = check_keyword_presence(
        task_texts.get("company_research", ""),
        raw.get("expected_keywords_research", []),
    )
    kw_followup = check_keyword_presence(
        follow_up_text,
        raw.get("expected_keywords_followup", []),
    )
    return {
        "task_completion_rate": round(completion.rate, 3),
        "completed_tasks": completion.completed_tasks,
        "total_tasks": completion.total_tasks,
        "failed_tasks": completion.failed_tasks,
        "join_point_discovery_questions_ok": join_points.discovery_questions_ok,
        "join_point_follow_up_actions_ok": join_points.follow_up_actions_ok,
        "join_points_all_ok": join_points.all_ok,
        "required_sections_present": sections.present,
        "required_sections_missing": sections.missing,
        "required_sections_all_present": sections.all_present,
        "stakeholders_found": stakeholders.found,
        "stakeholders_missing": stakeholders.missing,
        "stakeholder_coverage_rate": round(stakeholders.coverage_rate, 3),
        "keywords_research_found": kw_research.found,
        "keywords_research_missing": kw_research.missing,
        "keywords_followup_found": kw_followup.found,
        "keywords_followup_missing": kw_followup.missing,
    }


def run_all_workflows_sync(raw_cases: list[dict]) -> tuple[dict[str, str], dict[str, dict]]:
    """PHASE 1 — fully synchronous, no asyncio anywhere in this function or
    anything it calls. Runs the real workflow for every eval case and
    computes deterministic metrics. Must complete BEFORE main() ever calls
    asyncio.run() (see module docstring / _run_workflow_and_collect_sync).

    Returns:
        (follow_up_texts, side_metrics) — both keyed by case id.
    """
    follow_up_texts: dict[str, str] = {}
    side_metrics: dict[str, dict] = {}

    for raw in raw_cases:
        print(f"\n[{raw['id']}] Ejecutando workflow completo...")
        follow_up_text, extra = _run_workflow_and_collect_sync(raw)
        print(f"[{raw['id']}] Workflow terminado.")

        follow_up_texts[raw["id"]] = follow_up_text
        side_metrics[raw["id"]] = _compute_side_metrics(
            raw, follow_up_text, extra["wf_data"], extra["task_texts"]
        )

    return follow_up_texts, side_metrics


def _build_task_fn(follow_up_texts: dict[str, str]):
    """PHASE 2 helper — returns an async task function for strands-evals'
    Experiment. By this point every workflow has already run (Phase 1, fully
    sync, no asyncio involved). This function does NOT run the workflow —
    it only looks up the already-computed follow_up_actions text, so no new
    LiteLLM async client usage happens here beyond what the judge evaluators
    themselves need (which is fine, since THEY are the reason asyncio.run()
    exists in this script at all)."""

    async def task_fn(case: Case) -> str:
        return follow_up_texts[case.name]

    return task_fn


async def run_judge_evaluations_async(raw_cases: list[dict], follow_up_texts: dict[str, str]):
    """PHASE 2 — the only part of this script that runs inside asyncio.run().
    Only does LLM-as-judge scoring against already-computed text; never
    touches the `workflow` tool."""
    model_cfg = get_model_config()
    # Build a judge model compatible with strands-evals' evaluator `model=` param.
    if MODEL_PROVIDER == "gemini":
        from strands.models import LiteLLMModel
        judge_model = LiteLLMModel(**model_cfg["model_settings"])
    else:
        from strands.models import OllamaModel
        judge_model = OllamaModel(**model_cfg["model_settings"])

    sdk_cases = [
        Case(
            name=c["id"],
            input=json.dumps(c["input"], ensure_ascii=False),
            expected_output=", ".join(c.get("expected_sections", [])),
        )
        for c in raw_cases
    ]

    task_fn = _build_task_fn(follow_up_texts)

    evaluators = [
        OutputEvaluator(rubric=_FOLLOW_UP_RUBRIC, model=judge_model),
        OutputEvaluator(
            rubric=_HELPFULNESS_RUBRIC,
            model=judge_model,
            name="HelpfulnessEvaluator",
        ),
    ]

    print("\nCorriendo evaluadores LLM-as-judge...")
    experiment = Experiment(cases=sdk_cases, evaluators=evaluators)
    return await experiment.run_evaluations_async(task=task_fn)


def main() -> None:
    raw_cases = _load_cases()
    print(f"Corriendo evals sobre {len(raw_cases)} caso(s) — esto puede tardar varios minutos por caso.")

    # ── PHASE 1: run every workflow, fully sync, zero asyncio involved ──────────
    follow_up_texts, side_metrics = run_all_workflows_sync(raw_cases)

    # ── PHASE 2: LLM-as-judge scoring, only NOW does asyncio.run() start ────────
    report = asyncio.run(run_judge_evaluations_async(raw_cases, follow_up_texts))

    # ── Print results ──────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"Workflow Evaluation Report  |  provider: {MODEL_PROVIDER}")
    print("=" * 60)

    case_evals: dict[str, list[dict]] = {}
    for case_item, score, reason in zip(report.cases, report.scores, report.reasons):
        cname = case_item.get("name", "unknown")
        eval_name = case_item.get("evaluator", case_item.get("evaluator_type", "Evaluator"))
        case_evals.setdefault(cname, []).append(
            {"name": eval_name, "score": score, "reasoning": reason}
        )

    for cname, ev_list in case_evals.items():
        print(f"\nCase: {cname}")
        for ev in ev_list:
            reason_str = str(ev["reasoning"])
            truncated = reason_str[:140] + "…" if len(reason_str) > 140 else reason_str
            print(f"  [{ev['name']}]  score={ev['score']:.2f}  reasoning={truncated}")

        dm = side_metrics.get(cname, {})
        print(
            f"  [task_completion]       "
            f"{dm.get('completed_tasks')}/{dm.get('total_tasks')} tasks  "
            f"rate={dm.get('task_completion_rate'):.2f}  "
            f"failed={dm.get('failed_tasks')}"
        )
        print(
            f"  [join_points]           "
            f"discovery_questions={dm.get('join_point_discovery_questions_ok')}  "
            f"follow_up_actions={dm.get('join_point_follow_up_actions_ok')}"
        )
        print(
            f"  [required_sections]     "
            f"present={dm.get('required_sections_present')}  "
            f"missing={dm.get('required_sections_missing')}"
        )
        print(
            f"  [stakeholder_coverage]  "
            f"found={dm.get('stakeholders_found')}  "
            f"missing={dm.get('stakeholders_missing')}  "
            f"rate={dm.get('stakeholder_coverage_rate'):.2f}"
        )
        print(
            f"  [keywords_research]     "
            f"found={dm.get('keywords_research_found')}  "
            f"missing={dm.get('keywords_research_missing')}"
        )
        print(
            f"  [keywords_followup]     "
            f"found={dm.get('keywords_followup_found')}  "
            f"missing={dm.get('keywords_followup_missing')}"
        )

    # ── Export full report ─────────────────────────────────────────────────────
    output: list[dict] = []
    for cname, ev_list in case_evals.items():
        entry: dict = {"case": cname, "evaluators": ev_list}
        entry.update(side_metrics.get(cname, {}))
        output.append(entry)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUTS_DIR / f"{REPORT_FILENAME_PREFIX}_{timestamp}.json"
    report_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nFull report written to: {report_path}")


if __name__ == "__main__":
    main()
