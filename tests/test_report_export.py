"""Tests for src/utils/report_export.py and src/workflow/deliverable.py"""

import json

import pytest

from src.utils.report_export import write_report
from src.workflow import deliverable as deliverable_module
from src.workflow.deliverable import build_markdown_report, extract_task_text, load_workflow_json

MOCK_WORKFLOW = {
    "workflow_id": "demo_test",
    "status": "completed",
    "task_results": {
        "company_research": {"status": "completed", "result": [{"text": "Acme is a logistics company."}]},
        "stakeholder_mapping": {"status": "completed", "result": [{"text": "Jane cares about lock-in."}]},
        "meeting_summary": {"status": "completed", "result": [{"text": "Discussed timeline."}]},
        "discovery_questions": {"status": "completed", "result": [{"text": "What is your migration timeline?"}]},
        "follow_up_actions": {"status": "completed", "result": [{"text": "Send follow-up email to Jane."}]},
    },
}


@pytest.fixture
def mock_workflow_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(deliverable_module, "WORKFLOW_DIR", tmp_path)
    path = tmp_path / "demo_test.json"
    path.write_text(json.dumps(MOCK_WORKFLOW), encoding="utf-8")
    return tmp_path


def test_load_workflow_json_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(deliverable_module, "WORKFLOW_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        load_workflow_json("nonexistent")


def test_load_workflow_json_reads_persisted_state(mock_workflow_dir):
    data = load_workflow_json("demo_test")
    assert data["workflow_id"] == "demo_test"


def test_extract_task_text_returns_text_for_completed_task(mock_workflow_dir):
    data = load_workflow_json("demo_test")
    text = extract_task_text(data, "follow_up_actions")
    assert text == "Send follow-up email to Jane."


def test_extract_task_text_returns_none_for_missing_task(mock_workflow_dir):
    data = load_workflow_json("demo_test")
    assert extract_task_text(data, "does_not_exist") is None


def test_extract_task_text_returns_none_for_pending_task(mock_workflow_dir):
    data = load_workflow_json("demo_test")
    data["task_results"]["follow_up_actions"]["status"] = "pending"
    assert extract_task_text(data, "follow_up_actions") is None


def test_build_markdown_report_includes_both_join_points(mock_workflow_dir):
    report = build_markdown_report("demo_test")
    assert "What is your migration timeline?" in report
    assert "Send follow-up email to Jane." in report


def test_build_markdown_report_includes_all_phase1_outputs(mock_workflow_dir):
    report = build_markdown_report("demo_test")
    assert "Acme is a logistics company." in report
    assert "Jane cares about lock-in." in report
    assert "Discussed timeline." in report


def test_write_report_creates_file_with_content(tmp_path, monkeypatch):
    monkeypatch.setattr("src.utils.report_export.OUTPUTS_DIR", tmp_path)
    path = write_report("# Hello", "demo_test")
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "# Hello"
    assert path.parent == tmp_path
