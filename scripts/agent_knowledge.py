#!/usr/bin/env python3
"""Lo que los agentes saben de Vicente, en una nota de Obsidian, con caducidad.

Fuentes:
- PROFILE.md (fuente única del perfil; ~/.claude/PROFILE.md es un symlink al
  vault Visi-Personal). Cada sección lleva `_Revisado: AAAA-MM-DD_`.
- Memorias automáticas de Claude Code de tipo user/feedback, repartidas en
  ~/.claude/projects/*/memory/.

Escribe `<Visi-Personal>/perfil/Lo que saben los agentes.md`. Con `--hook`
funciona como SessionStart: además inyecta un aviso si alguna sección del
perfil está caducada, para que el agente no la dé por vigente.

Caducidad: "Proyectos activos" a los 30 días, el resto a los 90.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

MARK = "<!-- generado por apex/scripts/agent_knowledge.py: no editar, se reescribe en cada sesión -->"
NOTE_NAME = "Lo que saben los agentes.md"
STALE_DAYS = {"Proyectos activos": 30}
DEFAULT_STALE_DAYS = 90
_REVIEWED = re.compile(r"_Revisado: (\d{4}-\d{2}-\d{2})_")


def profile_path() -> Path:
    return Path(os.environ.get("APEX_PROFILE_PATH", Path.home() / ".claude" / "PROFILE.md"))


def memory_root() -> Path:
    return Path(os.environ.get("APEX_MEMORY_ROOT", Path.home() / ".claude" / "projects"))


def personal_vault() -> Path:
    return Path(os.environ.get("APEX_PERSONAL_VAULT", Path.home() / "Documentos" / "Visi-Personal"))


def profile_sections(text: str, today: date) -> list[dict]:
    """Secciones `## ` del perfil con su fecha de revisión y si están caducadas."""
    out = []
    for m in re.finditer(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        title, body = m.group(1).strip(), m.group(2)
        rev = _REVIEWED.search(body)
        limit = STALE_DAYS.get(title, DEFAULT_STALE_DAYS)
        if rev:
            age = (today - date.fromisoformat(rev.group(1))).days
            out.append({"title": title, "reviewed": rev.group(1), "age": age, "limit": limit,
                        "stale": age > limit})
        else:
            out.append({"title": title, "reviewed": None, "age": None, "limit": limit, "stale": True})
    return out


def _frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    fm = {}
    for line in text[4:end].splitlines():
        m = re.match(r"^\s*(name|description|type):\s*(.+)$", line)
        if m:
            fm.setdefault(m.group(1), m.group(2).strip().strip("'\""))
    return fm


def _origin(project_dir: str) -> str:
    return project_dir.replace("-home-vicente-", "").replace("-home-vicente", "~").replace("-", "/", 1) or "~"


def memories() -> list[dict]:
    """Memorias user/feedback de todos los proyectos."""
    out = []
    for f in sorted(memory_root().glob("*/memory/*.md")):
        if f.name == "MEMORY.md":
            continue
        try:
            fm = _frontmatter(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        if fm.get("type") not in ("user", "feedback"):
            continue
        out.append({"name": fm.get("name", f.stem), "description": fm.get("description", ""),
                    "type": fm["type"], "origin": _origin(f.parent.parent.name), "path": str(f),
                    "date": datetime.fromtimestamp(f.stat().st_mtime).date().isoformat(),
                    "key": re.sub(r"[^a-z0-9]+", "-", fm.get("name", f.stem).lower()).strip("-")})
    return out


def render(sections: list[dict], mems: list[dict], today: date) -> str:
    lines = [MARK, "# Lo que saben los agentes", "",
             f"Generado el {today.isoformat()}. Claude Code y Codex leen el [[PROFILE]] como fuente",
             "única; además, Claude guarda memorias sueltas por proyecto, listadas abajo.", "",
             "## Perfil: estado de cada sección", "",
             "| Sección | Revisado | Estado |", "|---|---|---|"]
    for s in sections:
        estado = (f"**POR REVISAR** (hace {s['age']} días, caduca a los {s['limit']})" if s["stale"] and s["age"] is not None
                  else "**POR REVISAR** (sin fecha)" if s["stale"] else f"vigente (hace {s['age']} días)")
        lines.append(f"| {s['title']} | {s['reviewed'] or '—'} | {estado} |")

    groups: dict[str, list[dict]] = {}
    for m in mems:
        groups.setdefault(m["key"], []).append(m)
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    lines += ["", f"## Memorias sueltas ({len(mems)})", "",
              "Candidatas a consolidar en el perfil o a borrar. Tipo `user` = quién eres;",
              "`feedback` = cómo quieres que se trabaje.", ""]
    if dups:
        lines += [f"### Repetidas en varios proyectos ({len(dups)})", ""]
        for k, v in sorted(dups.items()):
            lines.append(f"- **{v[0]['name']}** · en {len(v)}: " + ", ".join(f"{m['origin']} ({m['date']})" for m in v))
        lines.append("")
    for kind, title in (("user", "Sobre ti"), ("feedback", "Cómo trabajar contigo")):
        items = sorted((m for m in mems if m["type"] == kind), key=lambda m: m["date"], reverse=True)
        lines += [f"### {title} ({len(items)})", ""]
        lines += [f"- **{m['name']}** · {m['origin']} · {m['date']}  \n  {m['description']}" for m in items] or ["Ninguna."]
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    hook = "--hook" in argv
    if hook:
        try:
            json.load(sys.stdin)
        except (ValueError, OSError):
            pass
    today = date.fromisoformat(os.environ["APEX_TODAY"]) if os.environ.get("APEX_TODAY") else date.today()
    prof = profile_path()
    if not prof.exists():
        return 0
    sections = profile_sections(prof.read_text(encoding="utf-8"), today)

    folder = personal_vault() / "perfil"
    if folder.is_dir():
        note = folder / NOTE_NAME
        content = render(sections, memories(), today)
        existing = note.read_text(encoding="utf-8") if note.exists() else None
        if existing is None or (existing.startswith(MARK) and existing != content):
            note.write_text(content, encoding="utf-8")

    stale = [s for s in sections if s["stale"]]
    if hook and stale:
        detail = "; ".join(f"{s['title']} (revisada {s['reviewed'] or 'nunca'})" for s in stale)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "## Perfil de Vicente: secciones caducadas\n\n"
                f"En `~/.claude/PROFILE.md` están sin revisar: {detail}. No des por vigente lo que "
                "dicen: si lo necesitas, pregunta a Vicente primero. Cuando confirme o corrija, "
                "actualiza la sección y su línea `_Revisado: AAAA-MM-DD_`."),
        }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
