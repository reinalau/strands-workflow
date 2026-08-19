"""Console-to-file logging: mirrors everything printed to stdout AND stderr
into logs/run_<timestamp>.log, so each workflow run leaves a full trace.

IMPORTANT #1: Python's `logging` module writes to stderr by default (via
logging.StreamHandler()'s default stream). A tee that only wraps stdout
misses every logger.info/debug/error line — which is most of what's
interesting to a reader analyzing what the workflow actually did. This tees
both streams.

IMPORTANT #2 (verified empirically with OLLAMA_NUM_PARALLEL > 1): once tasks
genuinely run concurrently, multiple threads stream tokens to stdout at the
same time (Strands' default callback_handler prints as tokens arrive). A
plain, unlocked write() interleaves those writes character-by-character,
producing garbled output in both the console and the log file — this is NOT
a data corruption issue in Ollama/Strands, it's a thread-safety bug in the
tee itself. Fixed with a threading.Lock around every write().
"""

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class _Tee:
    def __init__(self, *streams):
        self.streams = streams
        self._lock = threading.Lock()

    def write(self, data):
        # Lock the whole write across all destination streams so that a
        # write from one thread can't get interleaved with a write from
        # another thread mid-line (observed with concurrent Ollama tasks).
        with self._lock:
            for s in self.streams:
                s.write(data)
                s.flush()

    def flush(self):
        with self._lock:
            for s in self.streams:
                s.flush()


def tee_console_to_file() -> Path:
    """Redirect stdout AND stderr to also write into a timestamped log file.
    Returns the log file path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS_DIR / f"run_{timestamp}.log"
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)
    return log_path


def configure_debug_logging(level=logging.DEBUG) -> None:
    """Enable strands/strands_tools logging on stdout (thus also captured by
    the tee). DEBUG by default so the reader sees each task's
    "Executing task X..." line (start-ish) in addition to "Task X
    completed" (end) — bracketing every task's real execution window.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )