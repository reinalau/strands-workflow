"""Writes the final .md deliverable to outputs/."""

from datetime import datetime
from pathlib import Path

OUTPUTS_DIR = Path(__file__).resolve().parents[2] / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)


def write_report(content: str, workflow_id: str) -> Path:
    """Write the markdown report to outputs/<workflow_id>_<timestamp>.md
    and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUTS_DIR / f"{workflow_id}_{timestamp}.md"
    path.write_text(content, encoding="utf-8")
    return path
