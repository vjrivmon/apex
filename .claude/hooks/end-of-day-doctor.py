#!/usr/bin/env python3
"""UserPromptSubmit hook — dispara Apex-doctor + handoff cuando detecta
frase de cierre o sesión >SESSION_AGE_THRESHOLD horas (Sprint 13).

NO bloquea. Sólo informa via stdout (additionalContext que el agente lee al
construir su próxima respuesta).

Triggers:

- (A) `wrapup_phrase`: el último prompt contiene alguna frase de
  `lib/wrapup_phrases.py` (ej. "he acabado por hoy").
- (B) `session_age`: han pasado >APEX_DOCTOR_SESSION_AGE_HOURS (default 3.5h)
  desde el primer prompt de esta sesión. Útil para anticiparse al límite de
  sesión de Claude Code MAX (~5h por ventana).

Lo que hace cuando dispara:

1. Inserta `session_starts(session_id)` si no existe (para que el siguiente
   tick pueda calcular la edad).
2. Throttle: si `apex_doctor.is_throttled` (último run hace <1h), salta el
   doctor pero igualmente avisa al agente.
3. Ejecuta `apex_doctor.run_doctor(project_root, trigger=...)` con timeout
   wall-clock 8s.
4. Escribe handoff llamando al MCP equivalente in-process: serializa el
   estado actual a `.apex/handoff/{session_id}.md`.
5. Imprime a stdout un bloque con resumen del run + ruta del MD para que el
   agente lo mencione antes de cerrar.

Convención hooks Claude Code (UserPromptSubmit):
- stdin: JSON con `prompt`, `session_id`, `transcript_path`, `cwd`.
- stdout: texto que se inyecta como contexto adicional.
- exit 0 = continúa.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "lib"))

# Imports separados: si `context_db` (aiosqlite) falla en el python que
# ejecuta el hook, el doctor sigue funcionando y solo se degrada el handoff.
# Antes esto era un único `except` que mataba TODO si fallaba cualquier
# import → hook silencioso → bug latente del Sprint 13.
try:
    import apex_doctor as _doc
    import wrapup_phrases as _wp
except Exception:
    _doc = None  # type: ignore
    _wp = None  # type: ignore

try:
    import handoff as _ho
    from context_db import ApexContextDB
except Exception:
    _ho = None  # type: ignore
    ApexContextDB = None  # type: ignore


SESSION_AGE_HOURS = float(
    os.environ.get("APEX_DOCTOR_SESSION_AGE_HOURS", "3.5")
)
DOCTOR_TIMEOUT_S = float(
    os.environ.get("APEX_DOCTOR_TIMEOUT_S", "8.0")
)
HANDOFF_HARD_TIMEOUT_S = float(
    os.environ.get("APEX_HANDOFF_TIMEOUT_S", "3.0")
)


def _find_project_root(cwd: Path) -> Path | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex" / "context.db").exists():
            return parent
    return None


async def _write_handoff(project_root: Path, session_id: str,
                          transcript_path: str) -> Path | None:
    if _ho is None or ApexContextDB is None:
        return None
    db_path = project_root / ".apex" / "context.db"
    db = ApexContextDB(str(db_path))
    try:
        await db.initialize()
    except Exception:
        return None
    try:
        tokens = _ho.estimate_tokens_in_transcript(transcript_path) if transcript_path else 0
        path = await _ho.serialize_handoff(project_root, session_id, db,
                                             transcript_tokens=tokens)
        return path
    except Exception:
        return None


def main() -> int:
    if _doc is None or _wp is None:
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    prompt = (payload.get("prompt") or "").strip()
    session_id = (payload.get("session_id") or "").strip()
    transcript_path = payload.get("transcript_path") or ""
    cwd_raw = payload.get("cwd") or os.getcwd()
    project_root = _find_project_root(Path(cwd_raw))
    if project_root is None:
        return 0

    db_path = _doc.context_db_path(project_root)

    # 1) Registra inicio de sesión la primera vez que vemos este session_id
    if session_id:
        _doc.record_session_start(db_path, session_id)

    # 2) Detecta triggers
    matched = _wp.matched_phrase(prompt) if prompt else None
    triggered_by_age = False
    age_seconds = _doc.session_age_seconds(db_path, session_id) if session_id else None
    if age_seconds is not None and age_seconds >= SESSION_AGE_HOURS * 3600:
        triggered_by_age = True

    if not matched and not triggered_by_age:
        return 0

    trigger = "wrapup_phrase" if matched else "session_age"

    # 3) Throttle preview (sin correr todavía)
    if _doc.is_throttled(db_path):
        sys.stdout.write(
            "\n[apex-doctor] Detectado cierre"
            f" ({trigger}={'\"' + matched + '\"' if matched else f'{age_seconds/3600:.1f}h'}),"
            " pero el doctor corrió hace <1h. Salto la ejecución.\n"
            "  Si quieres forzar: `apex_doctor_run(force=True)`.\n"
        )
        return 0

    # 4) Doctor + handoff con timeout wall-clock
    t0 = time.monotonic()
    try:
        run = _doc.run_doctor(project_root, trigger=trigger, force=False)
    except Exception as exc:
        sys.stdout.write(
            f"\n[apex-doctor] Falló al ejecutar: {exc}\n"
        )
        return 0

    elapsed = time.monotonic() - t0
    if elapsed > DOCTOR_TIMEOUT_S:
        sys.stdout.write(
            f"\n[apex-doctor] Tardó {elapsed:.1f}s (>{DOCTOR_TIMEOUT_S}s); "
            "resultados parciales escritos pero no inyectados completos.\n"
        )

    # 5) Handoff con timeout duro: aiosqlite puede colgarse si otra sesión
    #    Claude concurrente tiene el WAL bloqueado. Lo aislamos en un thread
    #    daemon con join timeout — si no termina, abandonamos el handoff y
    #    seguimos. El hook DEBE salir; si no, Claude declara timeout, trunca
    #    additionalContext, y la sesión muere.
    import threading
    handoff_path: Path | None = None
    if session_id:
        _result: list[Path | None] = [None]

        def _runner() -> None:
            try:
                _result[0] = asyncio.run(
                    _write_handoff(project_root, session_id, transcript_path)
                )
            except Exception:
                _result[0] = None

        t = threading.Thread(target=_runner, daemon=True)
        t.start()
        t.join(timeout=HANDOFF_HARD_TIMEOUT_S)
        handoff_path = _result[0]

    # 6) Inyecta resumen al agente
    summary = _doc.short_summary(run)
    lines = [
        "",
        "[apex-doctor] cierre detectado",
        f"  trigger: {trigger}"
        + (f' ("{matched}")' if matched else f" (sesión ~{age_seconds/3600:.1f}h)" if age_seconds else ""),
        f"  {summary}",
    ]
    if handoff_path is not None:
        rel = handoff_path.relative_to(project_root) if handoff_path.is_relative_to(project_root) else handoff_path
        lines.append(f"  handoff: {rel}")
    if run.proposals_count > 0:
        lines.append(
            f"  Antes de cerrar: menciona a Vicente las {run.proposals_count} "
            "propuesta(s) del doctor y confirma que el handoff está listo."
        )
    else:
        lines.append(
            "  Antes de cerrar: confirma a Vicente que el doctor corrió sin "
            "hallazgos y que el handoff está listo."
        )
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
