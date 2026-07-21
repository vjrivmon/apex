"""Shared hook metrics for APEX hooks.

Every hook should call `start_hook()` at entry and `end_hook()` before exit.
Writes structured JSON lines to .apex/hook_metrics.jsonl.

Usage in a hook:
    from lib.hook_metrics import start_hook, end_hook
    _start = start_hook("context-watch")
    # ... hook logic ...
    end_hook("context-watch", _start, exit_code=0)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


def _find_apex_dir() -> Path | None:
    """Walk up from CWD to find .apex/ directory."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        apex_dir = parent / ".apex"
        if apex_dir.is_dir():
            return apex_dir
    return None


def start_hook(name: str) -> float:
    """Record hook start time. Returns monotonic start timestamp."""
    return time.monotonic()


def end_hook(
    name: str,
    start_ts: float,
    exit_code: int = 0,
    extra: dict | None = None,
) -> None:
    """Record hook completion metrics to .apex/hook_metrics.jsonl.

    Never raises -- metrics are best-effort.
    """
    try:
        elapsed_ms = round((time.monotonic() - start_ts) * 1000, 1)
        apex_dir = _find_apex_dir()
        if apex_dir is None:
            return

        metrics_file = apex_dir / "hook_metrics.jsonl"
        entry = {
            "hook": name,
            "elapsed_ms": elapsed_ms,
            "exit_code": exit_code,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            entry.update(extra)

        metrics_file.parent.mkdir(parents=True, exist_ok=True)
        with open(metrics_file, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # metrics never break the hook
