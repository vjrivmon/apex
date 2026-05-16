"""APEX MCP handler: forge."""
from __future__ import annotations
from typing import Any


async def handle_apex_skill_forge_scan(db: Any, arguments: dict) -> Any:
    """Handler for apex_skill_forge_scan."""
    project_root = _find_project_root()
    include_cp = bool(arguments.get("include_cross_project", True))
    hub_path = _HUB_DB if include_cp else None
    project_id = project_root.name
    patterns = _forge.scan_all(project_root, hub_db_path=hub_path,
                                project_id=project_id)
    written: list[str] = []
    existing: list[str] = []
    rejected: list[str] = []
    db_path = _forge.context_db_path(project_root)
    for pat in patterns:
        slug = pat.slug()
        if _forge.is_rejected(db_path, slug):
            rejected.append(slug)
            continue
        prop_path = _forge.proposals_dir(project_root) / f"{slug}.md"
        if prop_path.exists():
            existing.append(slug)
            continue
        _forge.write_proposal(_forge.propose(pat), project_root)
        written.append(slug)
    lines = [f"Skill Forge scan — {len(patterns)} patrón(es) detectado(s)"]
    if written:
        lines.append(f"  ○ propuestas nuevas ({len(written)}):")
        lines += [f"    - {s}" for s in written]
    if existing:
        lines.append(f"  · ya propuestos ({len(existing)}):")
        lines += [f"    - {s}" for s in existing]
    if rejected:
        lines.append(f"  ✗ rechazados previamente ({len(rejected)}):")
        lines += [f"    - {s}" for s in rejected]
    if not (written or existing or rejected):
        lines.append("  (sin patrones recurrentes detectados)")
    return [TextContent(type="text", text="\n".join(lines))]

async def handle_apex_skill_forge_approve(db: Any, arguments: dict) -> Any:
    """Handler for apex_skill_forge_approve."""
    project_root = _find_project_root()
    slug = arguments["slug"]
    skills_root = arguments.get("skills_root", "~/.claude/skills")
    target = _forge.approve(slug, project_root, skills_root=skills_root)
    return [TextContent(type="text", text=(
        f"○ Skill aprobado: {slug}\n  → {target}"
    ))]

async def handle_apex_skill_forge_reject(db: Any, arguments: dict) -> Any:
    """Handler for apex_skill_forge_reject."""
    project_root = _find_project_root()
    slug = arguments["slug"]
    reason = arguments["reason"]
    _forge.reject(slug, reason, project_root)
    return [TextContent(type="text", text=(
        f"✗ Skill rechazado: {slug}\n  motivo: {reason}"
    ))]

