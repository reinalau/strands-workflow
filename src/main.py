"""
Entry point for the Discovery Meeting Copilot workflow.

Usage:
    MODEL_PROVIDER=ollama python -m src.main
    MODEL_PROVIDER=gemini python -m src.main --input examples/sample_input.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before importing src.config, which reads env vars at import time

# MUST be set before the strands_tools import below — workflow.py reads this
# env var once, at import time, when constructing its ThreadPoolExecutor.
# Verified bug: litellm's module_level_aclient (shared async HTTP client used
# for Vertex/Gemini streaming) is a single global object, not keyed per event
# loop like the rest of litellm's client cache. When workflow.py runs 2+
# tasks concurrently (each thread with its own asyncio.run() loop), they race
# on this shared client and intermittently crash with "attached to a
# different loop" / asyncio.exceptions.CancelledError (BerriAI/litellm
# issues #7667, #24230 — confirmed open bugs, not fixable from our code).
# Forcing sequential execution for Gemini avoids the race entirely. Ollama is
# unaffected (doesn't use litellm's aiohttp transport), so it keeps real
# parallelism.
if os.getenv("MODEL_PROVIDER", "ollama").lower() == "gemini":
    os.environ.setdefault("STRANDS_WORKFLOW_MAX_THREADS", "1")

from strands import Agent
from strands_tools import workflow

from src.models.schemas import DiscoveryMeetingInput
from src.utils.logging_config import configure_debug_logging, tee_console_to_file
from src.utils.report_export import write_report
from src.workflow.builder import build_tasks
from src.workflow.deliverable import build_markdown_report
from src.workflow.instrumentation import install_task_timing_hooks

DEFAULT_INPUT_PATH = Path(__file__).resolve().parents[1] / "examples" / "sample_input.json"


def load_input(path: Path) -> DiscoveryMeetingInput:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return DiscoveryMeetingInput(**raw)


def run(input_path: Path, workflow_id: str = "discovery_meeting") -> Path:
    install_task_timing_hooks()
    meeting_input = load_input(input_path)

    tasks = build_tasks(
        company_name=meeting_input.company_name,
        known_challenges=meeting_input.known_challenges,
        stakeholders=meeting_input.stakeholders,
        raw_meeting_notes=meeting_input.raw_meeting_notes,
    )

    agent = Agent(tools=[workflow])

    print(f"Creating workflow '{workflow_id}' with {len(tasks)} tasks...")
    create_result = agent.tool.workflow(action="create", workflow_id=workflow_id, tasks=tasks)
    if create_result.get("status") != "success":
        print(create_result)
        sys.exit(1)

    print(f"Starting workflow '{workflow_id}'...")
    start_result = agent.tool.workflow(action="start", workflow_id=workflow_id)
    print(start_result["content"][0]["text"])

    print("Assembling final .md report from persisted task results...")
    report_md = build_markdown_report(workflow_id)
    report_path = write_report(report_md, workflow_id)

    agent.tool.workflow(action="delete", workflow_id=workflow_id)

    print(f"Report written to: {report_path}")
    return report_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Discovery Meeting Copilot workflow.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--workflow-id", type=str, default="discovery_meeting")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    tee_console_to_file()
    if args.debug:
        configure_debug_logging()

    run(args.input, args.workflow_id)
