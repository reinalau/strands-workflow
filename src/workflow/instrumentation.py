"""
Per-task start/end timestamp instrumentation.

Why this exists: verified in strands_tools.workflow source that per-task
start time is tracked ONLY in memory (WorkflowManager.task_executor.start_times)
and never logged or persisted — only `completed_at` is written to the
workflow's JSON. There is no public hook/callback exposed per task by the
`workflow` tool to observe this ourselves cleanly.

This module wraps (monkeypatches) `WorkflowManager.execute_task` at runtime,
in OUR OWN project code — the installed package files are never modified —
to print an explicit, readable start/end/duration line per task. This is
valuable for the article: it makes the DAG's real parallelism visible
directly in the log (multiple "START" lines close together = tasks running
concurrently).
"""

from datetime import datetime

from strands_tools import workflow as workflow_module

_original_execute_task = workflow_module.WorkflowManager.execute_task


def _instrumented_execute_task(self, task, wf):
    task_id = task["task_id"]
    start = datetime.now()
    print(f"[{start.isoformat(timespec='seconds')}] ▶ START  task='{task_id}'")

    result = _original_execute_task(self, task, wf)

    end = datetime.now()
    duration = (end - start).total_seconds()
    status = result.get("status", "unknown")
    print(
        f"[{end.isoformat(timespec='seconds')}] ⏹ END    task='{task_id}' "
        f"status={status} duration={duration:.1f}s"
    )
    return result


def install_task_timing_hooks() -> None:
    """Patch WorkflowManager.execute_task once, idempotently."""
    if workflow_module.WorkflowManager.execute_task is _original_execute_task:
        workflow_module.WorkflowManager.execute_task = _instrumented_execute_task
