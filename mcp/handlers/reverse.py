"""APEX MCP handler: reverse."""
from __future__ import annotations
from typing import Any


async def handle_apex_reverse_scan(db: Any, arguments: dict) -> Any:
    """Handler for apex_reverse_scan."""
    target = Path(arguments["path"]).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        return [TextContent(type="text", text=f"Path no existe o no es directorio: {target}")]

async def handle_apex_reverse_plan(db: Any, arguments: dict) -> Any:
    """Handler for apex_reverse_plan."""
    scan_report = arguments["scan_report"]
    answers = arguments.get("answers", {})
    # Construir ActionPlan: priorizar findings según severity y answers
    # a=skip, b=now, c=backlog, d=partial
    tasks = []
    for f in scan_report.get("findings", []):
        choice = answers.get(f["id"], "b")  # default: now
        if choice == "a":
            action = "skip"
        elif choice == "c":
            action = "backlog"
        elif choice == "d":
            action = "verify"
    return [TextContent(type='text', text='OK')]

async def handle_apex_onboard_apply(db: Any, arguments: dict) -> Any:
    """Handler for apex_onboard_apply."""
    target = Path(arguments["path"]).expanduser().resolve()
    scan_report = arguments["scan_report"]
    plan = arguments.get("plan", {})

    apex_dir = target / ".apex"
    wiki_dir = apex_dir / "wiki"
    created = []
    if not wiki_dir.exists():
        create_wiki(str(wiki_dir), project_name=target.name)
        created.append(str(wiki_dir))

    # Crear/inicializar context.db del proyecto target
    target_db_path = apex_dir / "context.db"
    from context_db import ApexContextDB
    target_db = ApexContextDB(str(target_db_path))
    await target_db.initialize()

    # Registrar meta
    await target_db.set_project_meta("project_name", target.name)
    await target_db.set_project_meta("onboarded_by", "apex_onboard_apply")
    from datetime import datetime, timezone
    await target_db.set_project_meta("onboarded_at", datetime.now(timezone.utc).isoformat())

    # Marcar fases según scan
    phase_count = 0
    for p in scan_report.get("phases", []):
        if isinstance(p["phase"], float) and p["phase"] == 10.5:
            continue  # 10.5 es gate, no fase en la tabla
        phase_num = int(p["phase"])
        status_map = {"completed": "completed", "partial": "in_progress", "missing": "pending", "unknown": "pending"}
        await target_db.set_phase(phase_num, status_map[p["status"]],
                                  notes=f"[retroactive] score={p['score']:.2f}. {'; '.join(p['evidence'][:2])}")
        phase_count += 1

    # Registrar findings como errores retroactivos (category=retroactive)
    findings_logged = 0
    for f in scan_report.get("findings", [])[:50]:
        await target_db.add_decision(
            category="retroactive",
            decision=f"[{f['id']}] {f['title']}",
            reasoning=f["detail"],
            phase=int(f["phase"]) if f["phase"] >= 0 and isinstance(f["phase"], (int, float)) and f["phase"] == int(f["phase"]) else 0,
        )
        findings_logged += 1

    # next_steps del plan
    tasks_logged = 0
    for t in plan.get("tasks", [])[:30]:
        if t["action"] in ("now", "verify"):
            priority = "high" if t["severity"] == "high" else "medium"
            await target_db.add_next_step(
                description=f"[{t['finding_id']}] {t['title']}",
                priority=priority,
            )
            tasks_logged += 1

    # Wiki: gap-analysis
    gap_md = "# Gap analysis\n\n"
    gap_md += f"Scan del {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
    gap_md += f"## Fases\n\n"
    for p in scan_report.get("phases", []):
        gap_md += f"- **{p['phase']} {p['name']}**: {p['status']} (score {p['score']:.2f})\n"
    gap_md += "\n## Findings críticos\n\n"
    for f in scan_report.get("findings", []):
        if f["severity"] == "high":
            gap_md += f"- {f['id']} (fase {f['phase']}): {f['detail']}\n"
    await target_db.add_wiki_page(
        slug="concepts/gap-analysis",
        title="Gap analysis",
        content=gap_md,
        page_type="concept",
        tags=["retroactive", "onboarding"],
    )
    (wiki_dir / "concepts").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "concepts" / "gap-analysis.md").write_text(gap_md, encoding="utf-8")

    await target_db.log_session(
        summary=f"Onboarded via reverse-engineer: {phase_count} fases, {findings_logged} findings, {tasks_logged} next_steps",
        key_outcomes=json.dumps({"phases": phase_count, "findings": findings_logged, "tasks": tasks_logged}),
        phase=0,
    )

    return [TextContent(type="text", text=(
        f"Onboard aplicado en {target}:\n"
        f"- {phase_count} fases marcadas\n"
        f"- {findings_logged} findings retroactivos registrados como decisiones\n"
        f"- {tasks_logged} tareas añadidas como next_steps\n"
        f"- Wiki: concepts/gap-analysis.md creado\n"
        f"- .apex/ listo para arrancar fase 12 (iteración)"
    ))]



async def handle_apex_research_competitor(db: Any, arguments: dict) -> Any:
    """Handler for apex_research_competitor."""
    url = arguments["url"]
    prefer_spa = arguments.get("prefer_spa", False)
    import research as _research
    signals = _research.summarize_competitor(url, prefer_spa=prefer_spa)
    md = _research.signals_to_markdown(signals)
    return [TextContent(type="text", text=md)]
