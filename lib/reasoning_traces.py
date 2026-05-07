"""APEX Sprint 15 — reasoning_traces.

Captura razonamiento en gates densos: 4 categorías iniciales (subset de las
15 de Hermes 3 / MIMO V2.5). El insumo del Advisor + corpus de SFT futuro.

Ver `.apex/sprints/sprint-15-advisor-blueprint.md` sección 3.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

# 4 categorías iniciales (las que más mapean al dolor cross-project APEX).
# Las otras 11 de Hermes entran en S16+ con datos reales.
TRACE_CATEGORIES_V1: frozenset[str] = frozenset({
    "cascading_failure_recovery",
    "socratic_self_correction",
    "multi_agent_coordination",
    "long_horizon_consequences",
})

GATE_KINDS: frozenset[str] = frozenset({
    "phase_close",
    "grader_blocking",
    "doctor_proposal",
    "override",
})

DELIBERATION_MIN_CHARS = 200
DELIBERATION_MAX_CHARS = 2000


def _conn(db_path: Path | str) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=5.0)


def log_trace(
    db_path: Path | str,
    session_id: str,
    phase: int | None,
    category: str,
    gate_kind: str,
    deliberation: str,
    calibration_confidence: float,
    calibration_text: str,
    alternatives_considered: list[dict] | None,
) -> int:
    """Registra una traza de razonamiento. Valida invariantes antes de escribir.

    Raises:
        ValueError si la categoría/gate no son válidos, deliberation excede
        rango [200, 2000] chars, o confidence no está en [0, 1].
    """
    if category not in TRACE_CATEGORIES_V1:
        raise ValueError(
            f"invalid category: {category!r} not in {sorted(TRACE_CATEGORIES_V1)}"
        )
    if gate_kind not in GATE_KINDS:
        raise ValueError(
            f"invalid gate_kind: {gate_kind!r} not in {sorted(GATE_KINDS)}"
        )
    if not isinstance(deliberation, str):
        raise ValueError("deliberation must be str")
    n = len(deliberation)
    if n < DELIBERATION_MIN_CHARS or n > DELIBERATION_MAX_CHARS:
        raise ValueError(
            f"deliberation length {n} out of range "
            f"[{DELIBERATION_MIN_CHARS}, {DELIBERATION_MAX_CHARS}]"
        )
    try:
        conf = float(calibration_confidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("calibration_confidence must be float") from exc
    if conf < 0.0 or conf > 1.0:
        raise ValueError(f"calibration_confidence {conf} out of [0, 1]")
    alts_json = json.dumps(alternatives_considered or [], ensure_ascii=False)
    with _conn(db_path) as c:
        cur = c.execute(
            "INSERT INTO reasoning_traces "
            "(session_id, phase, category, gate_kind, deliberation, "
            " calibration_confidence, calibration_text, alternatives_considered) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, phase, category, gate_kind, deliberation,
                conf, calibration_text or "", alts_json,
            ),
        )
        c.commit()
        return int(cur.lastrowid)


def get_recent(
    db_path: Path | str,
    session_id: str,
    limit: int = 5,
) -> list[dict]:
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            "SELECT id, session_id, phase, category, gate_kind, deliberation, "
            "       calibration_confidence, calibration_text, "
            "       alternatives_considered, created_at "
            "FROM reasoning_traces "
            "WHERE session_id=? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]


def export_sharegpt(
    db_path: Path | str,
    project_path: str,
    output_path: str,
) -> int:
    """Exporta el corpus en formato ShareGPT (JSONL).

    Cada traza → conversation:
      [{from: human, value: <gate context>},
       {from: gpt,   value: deliberation + calibration + alternatives}]
    Compatible con OusiaResearch / axolotl / llamafactory.

    Returns:
        número de trazas exportadas.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            "SELECT id, session_id, phase, category, gate_kind, deliberation, "
            "       calibration_confidence, calibration_text, "
            "       alternatives_considered, created_at "
            "FROM reasoning_traces ORDER BY id ASC"
        )
        rows = cur.fetchall()
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            human = (
                f"[project={project_path}] [phase={r['phase']}] "
                f"[gate={r['gate_kind']}] [category={r['category']}] "
                f"[trace_id={r['id']}]"
            )
            gpt_parts: list[str] = [r["deliberation"]]
            if r["calibration_text"]:
                gpt_parts.append(
                    f"\n\nCalibración ({r['calibration_confidence']}): "
                    f"{r['calibration_text']}"
                )
            try:
                alts = json.loads(r["alternatives_considered"] or "[]")
            except json.JSONDecodeError:
                alts = []
            if alts:
                lines = [
                    f"- {a.get('option', '?')}: rechazada porque "
                    f"{a.get('rejected_because', '?')}"
                    for a in alts
                ]
                gpt_parts.append("\n\nAlternativas consideradas:\n" + "\n".join(lines))
            record: dict[str, Any] = {
                "id": r["id"],
                "category": r["category"],
                "gate_kind": r["gate_kind"],
                "conversations": [
                    {"from": "human", "value": human},
                    {"from": "gpt", "value": "".join(gpt_parts)},
                ],
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            n += 1
    return n


def prompt_for_trace(category: str, gate_kind: str) -> str:
    """Instrucción imperativa para inyectar a additionalContext desde hooks."""
    return (
        "Antes de cerrar este gate, registra una traza de razonamiento llamando "
        "`apex_log_trace(\n"
        f"   category=\"{category}\",\n"
        f"   gate_kind=\"{gate_kind}\",\n"
        "   deliberation=<200-2000 chars sobre cómo llegaste a esta decisión>,\n"
        "   calibration_confidence=<0.0-1.0>,\n"
        "   calibration_text=<por qué no estás 100%>,\n"
        "   alternatives_considered=<JSON array con 1-3 alternativas y "
        "por qué las descartaste>\n"
        ").\n"
        "Esta traza alimenta al Advisor y al corpus de SFT futuro."
    )
