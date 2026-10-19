"""APEX MCP handler: security."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from pathlib import Path
from mcp.types import TextContent
from scaffold_devops import ScaffoldOptions as _ScaffoldOptions
from apex_handlers._common import find_project_root as _find_project_root
from scaffold_devops import scaffold as _scaffold_devops
from security_gate import scaffold_templates as _scaffold_security_templates
from security_gate import check_gate as _check_security_gate
from security_gate import render_report as _render_security_report
from security_gate import verdict_from_report as _verdict_from_report
from security_gate import write_report as _write_security_report
from typing import Any


async def handle_apex_security_gate(db: Any, arguments: dict) -> Any:
    """Handler for apex_security_gate."""
    root = _find_project_root()
    if arguments.get("scaffold"):
        copied = _scaffold_security_templates(root)
        scaffold_msg = f"Scaffolded {len(copied)} archivos de templates AgentArmor.\n\n"
    else:
        scaffold_msg = ""
    report = _check_security_gate(root)
    md = _render_security_report(report)
    report_path = _write_security_report(report)
    status = "PASSED" if report.passed else "BLOCKED"
    # El veredicto es lo que convierte el informe en un gate: la transición a
    # la fase 11 lo lee, y sin él no había nada que consultar (auditoría del
    # 2026-10-19: el gate 10.5 no bloqueaba nada).
    if db is not None:
        verdict_id = await db.add_verdict(**_verdict_from_report(report))
        verdict_msg = f"\n(Veredicto del gate 10.5: #{verdict_id})"
    else:
        verdict_msg = (
            "\n(AVISO: sin BD del proyecto no se ha podido persistir el "
            "veredicto del gate 10.5; la entrada en la fase 11 sigue bloqueada.)"
        )
    return [TextContent(type="text", text=(
        f"{scaffold_msg}Security Gate: **{status}**\n\n{md}\n\n(Report: {report_path}){verdict_msg}"
    ))]

async def handle_apex_scaffold_devops(db: Any, arguments: dict) -> Any:
    """Handler for apex_scaffold_devops."""
    target = Path(arguments["target"]) if arguments.get("target") else _find_project_root()
    opts = _ScaffoldOptions(
        target=target,
        project_name=arguments["name"],
        stack=arguments.get("stack", "python"),
        deploy_target=arguments.get("deploy_target", "vercel"),
        port=int(arguments.get("port", 8000)),
        health_path=arguments.get("health_path", "/health"),
        with_monitoring=bool(arguments.get("with_monitoring", True)),
        overwrite=bool(arguments.get("overwrite", False)),
    )
    report = _scaffold_devops(opts)
    lines = [f"Scaffold DevOps en {target}:"]
    lines.append(f"- Copiados: {len(report.copied)}")
    for p in report.copied:
        lines.append(f"  + {p.relative_to(target)}")
    if report.skipped:
        lines.append(f"- Saltados ({len(report.skipped)}, ya existían):")
        for p in report.skipped:
            lines.append(f"  · {p.relative_to(target)}")
    return [TextContent(type="text", text="\n".join(lines))]

