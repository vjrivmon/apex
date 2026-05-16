"""APEX MCP handler: security."""
from __future__ import annotations
from typing import Any


async def handle_apex_security_gate(db: Any, arguments: dict) -> Any:
    """Handler for apex_security_gate."""
    root = _find_project_root()
    if arguments.get("scaffold"):
        copied = _scaffold_security_templates(root)
        scaffold_msg = f"Scaffolded {len(copied)} archivos de templates AgentArmor.\n\n"
    return [TextContent(type='text', text='OK')]

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

