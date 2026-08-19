"""Tests for src/workflow/instrumentation.py — verifies that
install_task_timing_hooks() logs a START/END line with duration for
each workflow task, without requiring a real LLM call."""

from unittest.mock import MagicMock

from strands_tools import workflow as workflow_module

from src.workflow.instrumentation import install_task_timing_hooks


def test_install_task_timing_hooks_is_idempotent():
    original = workflow_module.WorkflowManager.execute_task
    install_task_timing_hooks()
    patched_once = workflow_module.WorkflowManager.execute_task
    install_task_timing_hooks()
    patched_twice = workflow_module.WorkflowManager.execute_task
    assert patched_once is patched_twice
    assert patched_once is not original


def test_instrumented_execute_task_prints_start_and_end(monkeypatch, capsys):
    install_task_timing_hooks()

    fake_manager = MagicMock()
    fake_task = {"task_id": "fake_task"}
    fake_workflow = {}

    # Mock the underlying (real) execute_task this wrapper calls internally
    from src.workflow import instrumentation

    monkeypatch.setattr(
        instrumentation,
        "_original_execute_task",
        lambda self, task, wf: {"status": "success"},
    )

    workflow_module.WorkflowManager.execute_task(fake_manager, fake_task, fake_workflow)

    captured = capsys.readouterr()
    assert "START" in captured.out
    assert "fake_task" in captured.out
    assert "END" in captured.out
    assert "status=success" in captured.out
    assert "duration=" in captured.out
