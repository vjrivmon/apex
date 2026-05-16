"""APEX MCP handler: roles."""
from __future__ import annotations
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

