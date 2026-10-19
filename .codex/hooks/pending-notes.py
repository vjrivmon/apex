#!/usr/bin/env python3
"""SessionStart: trae al contexto los pendientes que Vicente apunta en Obsidian.

La nota vive en `<vault>/projects/<id>/pendientes.md`, junto a la ficha que
exporta apex-hub. `<id>` es el del hub: carpeta del proyecto en minúsculas,
espacios a guiones. Cada `- [ ] ...` de primer nivel es una tarea; las líneas
sangradas debajo son su detalle. `- [ ] !auto ...` se implementa sin esperar
confirmación.
# La raíz del repo debe estar en sys.path para importar lib.project_root:
# el hook puede ejecutarse desde cualquier cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


Inyecta TODAS las tareas abiertas (hasta que se marquen `- [x]`) y señala las
nuevas o modificadas desde la sesión anterior. Qué se vio ya se guarda como
huellas en `project_meta.pendientes_vistos` del context.db del proyecto.

Un hook solo añade contexto: Claude actúa con el primer mensaje de la sesión.
Sin `.apex/` propio no hace nada (nunca sube hasta el home).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# La raíz del repo debe estar en sys.path para importar lib.project_root:
# el hook puede ejecutarse desde cualquier cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

META_KEY = "pendientes_vistos"
TEMPLATE = """# Pendientes

Una tarea por línea. Se leen al abrir Claude Code en este proyecto.
Por defecto Claude explica lo que ha entendido, lista sus dudas y espera tu
confirmación del plan. Con `!auto` lo implementa directamente.

- [ ] Ejemplo: sustituye esta línea por tu primera tarea
- [ ] !auto Ejemplo de tarea que se implementa sin pedir confirmación
"""
_TASK = re.compile(r"^- \[( |x|X)\] (.*)$")


def vault_dir() -> Path:
    return Path(os.environ.get("APEX_VAULT_DIR", Path.home() / "Documents" / "ApexVault")).expanduser()


# La raiz del proyecto la resuelve lib/project_root.py, la implementacion UNICA.
# Antes cada hook traia su propia copia, con reglas distintas: seis de ellas
# no cortaban al llegar al home y resolvian ~/.apex/context.db (memoria global)
# como si fuera el contexto de un proyecto.
from lib.project_root import find_project_root


def project_id(root: Path) -> str:
    """Misma fórmula que apex-hub (scanner._project_id_from_path)."""
    return root.name.lower().replace(" ", "-")


def parse_tasks(text: str) -> list[dict]:
    """Tareas abiertas de primer nivel con su detalle sangrado."""
    tasks: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = _TASK.match(line)
        if m:
            current = None
            if m.group(1) == " ":
                body = m.group(2).strip()
                auto = body.startswith("!auto")
                current = {"text": body[len("!auto"):].strip() if auto else body, "auto": auto, "detail": []}
                tasks.append(current)
            continue
        if current is not None and line.startswith((" ", "\t")) and line.strip():
            current["detail"].append(line.rstrip())
        elif line.strip():
            current = None
    for t in tasks:
        raw = t["text"] + "\n" + "\n".join(d.strip() for d in t["detail"])
        t["hash"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return tasks


def _seen(db: Path) -> set[str]:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        row = con.execute("SELECT value FROM project_meta WHERE key = ?", (META_KEY,)).fetchone()
        con.close()
        return set(json.loads(row[0])) if row else set()
    except (sqlite3.Error, ValueError):
        return set()


def _save_seen(db: Path, hashes: set[str]) -> None:
    con = sqlite3.connect(str(db), timeout=3)
    con.execute("PRAGMA busy_timeout=3000")
    con.execute("INSERT OR REPLACE INTO project_meta (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (META_KEY, json.dumps(sorted(hashes))))
    con.commit()
    con.close()


def render(pid: str, note: Path, tasks: list[dict], seen: set[str]) -> str:
    lines = [
        f"## Pendientes del proyecto (Obsidian: projects/{pid}/pendientes.md)",
        "",
        f"Vicente apuntó estas tareas en `{note}`. Atiéndelas al empezar, antes de",
        "cualquier otra cosa, siguiendo este protocolo:",
        "",
        "1. En tu primera respuesta, para CADA tarea: explica con tus palabras qué has",
        "   entendido y declara explícitamente tus dudas. Si no tienes ninguna, escribe",
        "   \"Dudas: ninguna\". No lo omitas aunque la tarea parezca obvia.",
        "2. Tareas normales: presenta el plan y ESPERA su confirmación antes de tocar nada.",
        "3. Tareas `!auto`: tras la explicación, impleméntalas sin esperar. Si tienes",
        "   alguna duda, NO es auto: pregunta primero.",
        "4. Al terminar una tarea, márcala en la nota: cambia `- [ ]` por `- [x]` y añade",
        "   al final `(hecho AAAA-MM-DD, <commit corto>)`. No borres tareas ni reescribas",
        "   su texto.",
        "",
    ]
    for i, t in enumerate(tasks, 1):
        flags = []
        if t["auto"]:
            flags.append("!auto")
        if t["hash"] not in seen:
            flags.append("NUEVA o MODIFICADA desde la última sesión")
        suffix = f" [{' · '.join(flags)}]" if flags else ""
        lines.append(f"{i}. {t['text']}{suffix}")
        lines.extend(f"   {d.strip()}" for d in t["detail"])
    return "\n".join(lines)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    root = find_project_root(Path(payload.get("cwd") or os.getcwd()))
    if root is None:
        return 0
    pid = project_id(root)
    folder = vault_dir() / "projects" / pid
    if not vault_dir().is_dir():
        return 0
    note = folder / "pendientes.md"
    if not note.exists():
        # Se crea la plantilla para que aparezca en Obsidian lista para usar.
        folder.mkdir(parents=True, exist_ok=True)
        note.write_text(TEMPLATE, encoding="utf-8")
        return 0

    ejemplos = {t["hash"] for t in parse_tasks(TEMPLATE)}
    tasks = [t for t in parse_tasks(note.read_text(encoding="utf-8")) if t["hash"] not in ejemplos]
    if not tasks:
        return 0
    db = root / ".apex" / "context.db"
    seen = _seen(db)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": render(pid, note, tasks, seen),
    }}, ensure_ascii=False))
    try:
        _save_seen(db, {t["hash"] for t in tasks})
    except sqlite3.Error as exc:
        # No se pierde nada: la próxima sesión las volverá a marcar como nuevas.
        print(f"[apex pending-notes] no se pudo guardar el estado: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
