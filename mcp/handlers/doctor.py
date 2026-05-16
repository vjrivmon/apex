"""APEX MCP handler: doctor."""
from __future__ import annotations
from typing import Any


async def handle_apex_doctor_run(db: Any, arguments: dict) -> Any:
    """Handler for apex_doctor_run."""
    project_root = _find_project_root()
    run = _doctor.run_doctor(
        project_root,
        trigger=arguments.get("trigger", "manual"),
        force=bool(arguments.get("force", False)),
        hub_db=_HUB_DB if _HUB_DB.exists() else None,
    )
    lines = [_doctor.short_summary(run)]
    if run.status == "throttled":
        lines.append(f"  motivo: {run.skipped_reason}")
        lines.append("  fuerza con: apex_doctor_run(force=True)")
    elif run.status == "done":
        lines.append(
            f"  inicio: {run.started_at} | fin: {run.finished_at}"
        )
        if run.proposals_count > 0:
            rel = (
                Path(".apex") / "doctor" / f"{run.run_id:04d}.md"
            )
            lines.append(f"  report: {rel}")
            by_kind: dict[str, int] = {}
            for p in run.proposals:
                by_kind[p.kind] = by_kind.get(p.kind, 0) + 1
            for kind, count in by_kind.items():
                lines.append(f"    - {kind}: {count}")
    return [TextContent(type="text", text="\n".join(lines))]

