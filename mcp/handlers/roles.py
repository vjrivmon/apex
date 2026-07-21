"""APEX MCP handler: roles."""
from __future__ import annotations
from apex_handlers._common import find_project_root as _find_project_root

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from pathlib import Path
from mcp.types import TextContent
import roles as _roles
import json
import os
from typing import Any


async def handle_apex_install_roles(db: Any, arguments: dict) -> Any:
    """Handler for apex_install_roles."""
    agents_root_arg = arguments.get("agents_root") or "~/.claude/agents"
    agents_root = Path(os.path.expanduser(agents_root_arg))
    results = _roles.install_all(
        agents_root=agents_root,
        force=bool(arguments.get("force", False)),
    )
    lines = [f"Roles instalados en {agents_root}:"]
    for role_name, (path, status) in results.items():
        marker = {"written": "○", "skipped": "·", "overwritten": "↻"}.get(
            status, "?")
        lines.append(f"  {marker} {role_name} [{status}] → {path}")
    lines.append("")
    lines.append(
        "Para invocar: apex_invoke_role(role='apex-architect', "
        "phase=2, context_summary=...). El orquestador dispara el "
        "`Task` tool con el `subagent_type` devuelto."
    )
    return [TextContent(type="text", text="\n".join(lines))]

async def handle_apex_recommend_role(db: Any, arguments: dict) -> Any:
    """Handler for apex_recommend_role."""
    phase = int(arguments["phase"])
    role = _roles.recommended_for_phase(phase)
    reason = _roles.reason_for_phase(phase)
    installed = (
        _roles.is_installed(role) if role else False
    )
    payload = {
        "phase": phase,
        "phase_name": _roles.PHASE_NAMES.get(phase, "?"),
        "role": role,
        "installed": installed,
        "reason": reason,
    }
    text = (
        f"{reason}\n"
        f"Instalado: {'sí' if installed else 'no'}"
    )
    if role and not installed:
        text += "\n\nEjecuta apex_install_roles() antes de invocarlo."
    text += f"\n\n{json.dumps(payload, ensure_ascii=False)}"
    return [TextContent(type="text", text=text)]

async def handle_apex_invoke_role(db: Any, arguments: dict) -> Any:
    """Handler for apex_invoke_role."""
    role_name = arguments["role"]
    if role_name not in _roles.ROLES:
        return [TextContent(type="text", text=(
            f"Rol desconocido: {role_name}. "
            f"Disponibles: {', '.join(_roles.list_roles())}"
        ))]
    else:
        phase_arg = arguments.get("phase")
        phase_int = int(phase_arg) if phase_arg is not None else None
        project_root = _find_project_root()
        inv = _roles.build_invocation(
            role_name,
            phase=phase_int,
            context_summary=arguments.get("context_summary", ""),
            project_name=project_root.name,
            extra_instructions=arguments.get("extra_instructions", ""),
        )
        # Telemetría
        db_path = project_root / ".apex" / "context.db"
        inv_id = 0
        if db_path.exists():
            try:
                inv_id = _roles.record_invocation(
                    db_path,
                    role=role_name,
                    phase=phase_int,
                    session_id=arguments.get("session_id", ""),
                    context_summary=arguments.get("context_summary", "")[:500],
                    status="invoked",
                )
            except Exception:
                inv_id = 0
        installed = _roles.is_installed(role_name)
        lines = [
            f"Invocación preparada para {role_name} "
            f"(invocation_id={inv_id})",
            f"Instalado en ~/.claude/agents/: {'sí' if installed else 'no'}",
            "",
            "→ El orquestador (Claude Code main) debe ahora llamar:",
            "",
            f"Task(subagent_type=\"{inv['subagent_type']}\",",
            f"     description=\"{inv['description']}\",",
            "     prompt=<<<",
            inv["prompt"],
            ">>>)",
        ]
        if not installed:
            lines.append("")
            lines.append(
                "AVISO: el agente no está instalado. Ejecuta primero "
                "apex_install_roles()."
            )
        return [TextContent(type="text", text="\n".join(lines))]


