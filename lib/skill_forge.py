"""Skill Forge — auto-detector de patrones repetidos (Sprint 11.2).

Sin esperar invocación manual: tres detectores corren periódicamente desde un
hook PostToolUse y proponen skills concretas en `.apex/skill-proposals/`. La
aprobación es un solo comando (`apex_skill_forge_approve(slug)`) que mueve
el skill a `~/.claude/skills/<slug>/`. El rechazo registra el slug en BD para
no proponer lo mismo otra vez.

Detectores:

- **D1 grader-block** — mismo issue bloqueando en >=3 fases distintas → skill
  preventiva.
- **D2 tool-call pattern** — secuencia de N tools repetida >=5 veces → skill
  que compacta el flujo.
- **D3 cross-project** — misma decisión repetida en >=2 proyectos vía
  `hub.db` → skill global.

Diseño:

- Todas las funciones usan `sqlite3` síncrono, no `aiosqlite`. El hook que las
  invoca debe ser barato y no introducir overhead asyncio en cada PostToolUse.
- La detección NO es transaccional con la escritura de propuestas: si dos
  hooks corren a la vez generarán el mismo slug determinista y la segunda
  escritura sobreescribirá idempotentemente.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Constantes ────────────────────────────────────────────────────────────

D1_MIN_PHASES = 3            # Issue debe aparecer en >=3 fases distintas
D2_MIN_FREQ = 5              # Secuencia debe repetirse >=5 veces
D2_WINDOW = 3                # Tamaño de la secuencia (tripletes)
D2_MAX_LOG = 200             # Sólo mira los últimos N tool calls
D3_MIN_PROJECTS = 2          # Decisión debe aparecer en >=2 proyectos
D3_DECISIONS_LOOKBACK = 10   # Sólo mira las últimas N decisiones del proyecto


# ── Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class Pattern:
    """Patrón detectado por uno de los detectores."""
    detector: str                                   # grader_block | tool_call | cross_project
    signature: str                                  # Texto canónico (determina slug)
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0                         # 0..1

    def slug(self) -> str:
        sig_norm = re.sub(r"[^a-z0-9]+", "-", self.signature.lower()).strip("-")[:40]
        if not sig_norm:
            sig_norm = "pattern"
        h = hashlib.sha1(self.signature.encode("utf-8")).hexdigest()[:8]
        prefix = self.detector.replace("_", "-")
        return f"{prefix}-{sig_norm}-{h}"


@dataclass
class Proposal:
    """Propuesta de skill generada a partir de un Pattern."""
    pattern: Pattern
    title: str
    summary: str
    skill_md: str

    @property
    def slug(self) -> str:
        return self.pattern.slug()

    def to_markdown(self) -> str:
        ev = json.dumps(self.pattern.evidence, indent=2, ensure_ascii=False)
        return (
            f"# Skill Forge Proposal — {self.title}\n\n"
            f"- **Slug**: `{self.slug}`\n"
            f"- **Detector**: `{self.pattern.detector}`\n"
            f"- **Confianza**: {self.pattern.confidence:.2f}\n\n"
            f"## Resumen\n\n{self.summary}\n\n"
            f"## Evidencia\n\n```json\n{ev}\n```\n\n"
            f"## Draft de SKILL.md\n\n```markdown\n{self.skill_md}\n```\n\n"
            f"## Aprobar\n\n"
            f"`apex_skill_forge_approve(\"{self.slug}\")` mueve el skill a "
            f"`~/.claude/skills/{self.slug}/SKILL.md` y borra esta propuesta.\n\n"
            f"## Rechazar\n\n"
            f"`apex_skill_forge_reject(\"{self.slug}\", \"motivo\")` registra "
            f"el rechazo y borra esta propuesta. El mismo patrón no se volverá "
            f"a proponer.\n"
        )


# ── Helpers de path ───────────────────────────────────────────────────────

def context_db_path(project_root: Path | str) -> Path:
    return Path(project_root) / ".apex" / "context.db"


def proposals_dir(project_root: Path | str) -> Path:
    return Path(project_root) / ".apex" / "skill-proposals"


# ── Detectores ────────────────────────────────────────────────────────────

def _ro_conn(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None


def scan_grader_blocks(db_path: Path) -> list[Pattern]:
    """D1: issue bloqueante recurrente en >=D1_MIN_PHASES fases distintas."""
    conn = _ro_conn(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT phase, issues FROM grader_verdicts WHERE should_block=1"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    issue_to_phases: dict[str, set[int]] = defaultdict(set)
    for phase, issues_json in rows:
        try:
            issues = json.loads(issues_json or "[]")
        except (TypeError, json.JSONDecodeError):
            continue
        for iss in issues:
            if isinstance(iss, str):
                issue_to_phases[iss].add(int(phase))

    patterns: list[Pattern] = []
    for issue, phases in issue_to_phases.items():
        if len(phases) >= D1_MIN_PHASES:
            patterns.append(Pattern(
                detector="grader_block",
                signature=f"grader_block:{issue}",
                evidence={
                    "issue": issue,
                    "phases": sorted(phases),
                    "occurrences": len(phases),
                },
                confidence=min(1.0, len(phases) / 5.0),
            ))
    return patterns


def scan_tool_call_patterns(db_path: Path) -> list[Pattern]:
    """D2: secuencias de D2_WINDOW tools que se repiten >=D2_MIN_FREQ veces."""
    conn = _ro_conn(db_path)
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT tool FROM tool_call_log ORDER BY id DESC LIMIT ?",
            (D2_MAX_LOG,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    tools = [r[0] for r in reversed(rows)]
    if len(tools) < D2_WINDOW:
        return []

    seqs: Counter[tuple[str, ...]] = Counter()
    for i in range(len(tools) - D2_WINDOW + 1):
        seq = tuple(tools[i: i + D2_WINDOW])
        # Filtra ruido: misma tool repetida no es patrón interesante
        if len(set(seq)) == 1:
            continue
        seqs[seq] += 1

    patterns: list[Pattern] = []
    for seq, count in seqs.items():
        if count >= D2_MIN_FREQ:
            sig = "→".join(seq)
            patterns.append(Pattern(
                detector="tool_call",
                signature=f"tool_call:{sig}",
                evidence={"sequence": list(seq), "occurrences": count},
                confidence=min(1.0, count / 10.0),
            ))
    return patterns


def scan_cross_project_repeats(
    db_path: Path,
    hub_db_path: Path,
    project_id: str | None = None,
) -> list[Pattern]:
    """D3: decisiones recientes que aparecen en >=D3_MIN_PROJECTS proyectos."""
    local = _ro_conn(db_path)
    if local is None:
        return []
    try:
        decisions = local.execute(
            "SELECT category, decision FROM decisions "
            "WHERE invalid_from IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (D3_DECISIONS_LOOKBACK,),
        ).fetchall()
    except sqlite3.OperationalError:
        decisions = []
    finally:
        local.close()
    if not decisions:
        return []

    hub = _ro_conn(hub_db_path)
    if hub is None:
        return []

    patterns: list[Pattern] = []
    seen: set[str] = set()
    try:
        for category, decision in decisions:
            text = (decision or "").strip()
            if len(text) < 8:
                continue
            terms = [w for w in re.split(r"\W+", text) if len(w) >= 4][:4]
            if not terms:
                continue
            fts_q = " OR ".join(terms)
            try:
                rows = hub.execute(
                    "SELECT DISTINCT project_id FROM hub_search "
                    "WHERE hub_search MATCH ? AND source_type='decision' "
                    "LIMIT 10",
                    (fts_q,),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            projects = {r[0] for r in rows if r[0]}
            if project_id:
                projects.discard(project_id)
            if len(projects) < D3_MIN_PROJECTS:
                continue
            sig = f"cross_project:{category}:{text[:60]}"
            if sig in seen:
                continue
            seen.add(sig)
            patterns.append(Pattern(
                detector="cross_project",
                signature=sig,
                evidence={
                    "category": category,
                    "decision": text,
                    "shared_with_projects": sorted(projects),
                },
                confidence=min(1.0, len(projects) / 5.0),
            ))
    finally:
        hub.close()
    return patterns


# ── Builders de propuestas ────────────────────────────────────────────────

def _grader_block_skill(pattern: Pattern) -> Proposal:
    issue = pattern.evidence.get("issue", "unknown")
    phases = pattern.evidence.get("phases", [])
    title = f"Mitigar issue recurrente: {issue}"
    summary = (
        f"El grader detectó el issue `{issue}` bloqueando en {len(phases)} "
        f"fases ({', '.join(map(str, phases))}). Esta skill propone un "
        f"checklist preventivo para evitarlo proactivamente al inicio de "
        f"cada fase relevante."
    )
    skill_name = "avoid-" + re.sub(r"[^a-z0-9]+", "-", issue.lower()).strip("-")
    skill = (
        f"---\n"
        f"name: {skill_name}\n"
        f"description: Checklist preventivo contra el issue '{issue}' "
        f"detectado por el grader en {len(phases)} fases distintas.\n"
        f"---\n\n"
        f"# Avoid {issue}\n\n"
        f"Invocar al inicio de fases sensibles para verificar que no se "
        f"introduce el issue `{issue}`.\n\n"
        f"## Triggers\n\n"
        f"- Inicio de fase ∈ {{{', '.join(map(str, phases))}}}\n"
        f"- Antes de invocar `apex_grader_evaluate`\n\n"
        f"## Checklist\n\n"
        f"- [ ] Revisar issue específico: `{issue}`\n"
        f"- [ ] Confirmar que la condición que dispara el issue no aplica\n"
        f"- [ ] Documentar evidencia en `context.db` si aplica\n"
    )
    return Proposal(pattern=pattern, title=title, summary=summary, skill_md=skill)


def _tool_call_skill(pattern: Pattern) -> Proposal:
    seq = pattern.evidence.get("sequence", [])
    count = pattern.evidence.get("occurrences", 0)
    chain = " → ".join(seq)
    slug_hint = "-".join(re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
                         for t in seq)[:40]
    title = f"Compactar flujo: {chain}"
    summary = (
        f"Detectada secuencia repetida `{chain}` ({count} veces en últimas "
        f"{D2_MAX_LOG} llamadas). Esta skill propone una macro que compacta "
        f"los pasos en una sola invocación."
    )
    steps = "".join(f"{i+1}. `{t}`\n" for i, t in enumerate(seq))
    skill = (
        f"---\n"
        f"name: macro-{slug_hint}\n"
        f"description: Macro que compacta la secuencia recurrente "
        f"'{chain}' en un solo paso.\n"
        f"---\n\n"
        f"# Macro {chain}\n\n"
        f"## Por qué\n\n"
        f"Esta secuencia se ejecuta de forma consistente ({count} veces "
        f"detectadas).\n\n"
        f"## Pasos\n\n{steps}\n"
        f"## Cuándo usarlo\n\n"
        f"Cuando vayas a ejecutar `{seq[0]}` y haya intención de continuar "
        f"con `{seq[-1]}`.\n"
    )
    return Proposal(pattern=pattern, title=title, summary=summary, skill_md=skill)


def _cross_project_skill(pattern: Pattern) -> Proposal:
    cat = pattern.evidence.get("category", "general")
    dec = pattern.evidence.get("decision", "")
    projects = pattern.evidence.get("shared_with_projects", [])
    title = f"Decisión recurrente cross-project: {cat}"
    summary = (
        f"La decisión `{dec[:80]}` aparece en este proyecto y en "
        f"{', '.join(projects)}. Esta skill propone elevarla a guideline "
        f"global aplicable por defecto."
    )
    slug_hint = re.sub(r"[^a-z0-9]+", "-", cat.lower()).strip("-")[:30]
    proj_list = "".join(f"- {p}\n" for p in projects)
    skill = (
        f"---\n"
        f"name: global-{slug_hint}\n"
        f"description: Decisión recurrente cross-project sobre '{cat}'. "
        f"Aplicar por defecto a proyectos similares.\n"
        f"---\n\n"
        f"# Global {cat}\n\n"
        f"## Decisión\n\n{dec}\n\n"
        f"## Proyectos donde aparece\n\n{proj_list}\n"
        f"## Aplicación\n\n"
        f"Aplicar por defecto al iniciar proyectos de categoría `{cat}` "
        f"salvo que el usuario indique lo contrario.\n"
    )
    return Proposal(pattern=pattern, title=title, summary=summary, skill_md=skill)


_PROPOSAL_BUILDERS = {
    "grader_block": _grader_block_skill,
    "tool_call": _tool_call_skill,
    "cross_project": _cross_project_skill,
}


def propose(pattern: Pattern) -> Proposal:
    builder = _PROPOSAL_BUILDERS.get(pattern.detector)
    if builder is None:
        raise ValueError(f"Detector desconocido: {pattern.detector}")
    return builder(pattern)


# ── Persistencia de propuestas ────────────────────────────────────────────

def write_proposal(proposal: Proposal, project_root: Path | str) -> Path:
    out_dir = proposals_dir(project_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{proposal.slug}.md"
    path.write_text(proposal.to_markdown(), encoding="utf-8")
    return path


def list_proposals(project_root: Path | str) -> list[dict[str, Any]]:
    d = proposals_dir(project_root)
    if not d.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.md")):
        out.append({"slug": p.stem, "path": str(p), "size": p.stat().st_size})
    return out


def is_rejected(db_path: Path, slug: str) -> bool:
    conn = _ro_conn(db_path)
    if conn is None:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM skill_forge_rejections WHERE slug=?", (slug,)
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


# ── Logging de tool calls (alimenta D2) ──────────────────────────────────

def log_tool_call(project_root: Path | str, tool: str,
                  args_summary: str = "") -> None:
    """Inserta una entrada en `tool_call_log`. Best-effort: si la BD no existe
    o el schema no está migrado, no bloquea ni levanta excepciones."""
    db = context_db_path(project_root)
    if not db.exists():
        return
    try:
        conn = sqlite3.connect(str(db))
    except sqlite3.OperationalError:
        return
    try:
        conn.execute(
            "INSERT INTO tool_call_log (tool, args_summary) VALUES (?, ?)",
            (tool, args_summary[:200]),
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


# ── Aprobar / rechazar ────────────────────────────────────────────────────

def _extract_skill_block(proposal_md: str) -> str | None:
    # Sprint 11.3: proposals con SKILL.md descargados pueden contener bloques
    # ``` propios, así que el delimitador externo usa 4 backticks. Se busca
    # primero y se cae a 3 para mantener compat con proposals del Sprint 11.2.
    m = re.search(r"````markdown\n(.*?)\n````", proposal_md, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"```markdown\n(.*?)\n```", proposal_md, re.DOTALL)
    return m.group(1) if m else None


def approve(
    slug: str,
    project_root: Path | str,
    skills_root: Path | str = "~/.claude/skills",
) -> Path:
    src = proposals_dir(project_root) / f"{slug}.md"
    if not src.exists():
        raise FileNotFoundError(f"Propuesta no encontrada: {slug}")
    skills_root = Path(skills_root).expanduser()
    target_dir = skills_root / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "SKILL.md"
    raw = src.read_text(encoding="utf-8")
    skill_md = _extract_skill_block(raw) or raw
    target.write_text(skill_md, encoding="utf-8")
    src.unlink()
    return target


def reject(slug: str, reason: str, project_root: Path | str) -> None:
    db = context_db_path(project_root)
    if not db.exists():
        raise FileNotFoundError(f"Context DB no encontrada: {db}")
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT OR REPLACE INTO skill_forge_rejections "
            "(slug, reason, rejected_at) VALUES (?, ?, datetime('now'))",
            (slug, reason),
        )
        conn.commit()
    finally:
        conn.close()
    p = proposals_dir(project_root) / f"{slug}.md"
    if p.exists():
        p.unlink()


# ── Orquestador (usado por hook y por MCP scan) ──────────────────────────

def scan_all(
    project_root: Path | str,
    hub_db_path: Path | str | None = None,
    project_id: str | None = None,
) -> list[Pattern]:
    db = context_db_path(project_root)
    patterns: list[Pattern] = []
    patterns += scan_grader_blocks(db)
    patterns += scan_tool_call_patterns(db)
    if hub_db_path is not None:
        patterns += scan_cross_project_repeats(db, Path(hub_db_path), project_id)
    return patterns


def scan_and_write(
    project_root: Path | str,
    hub_db_path: Path | str | None = None,
    project_id: str | None = None,
) -> list[Path]:
    """Ejecuta los detectores y escribe propuestas nuevas. Devuelve los paths
    escritos en este pase (no incluye propuestas ya existentes ni rechazadas)."""
    db = context_db_path(project_root)
    written: list[Path] = []
    for pat in scan_all(project_root, hub_db_path, project_id):
        slug = pat.slug()
        if is_rejected(db, slug):
            continue
        prop_path = proposals_dir(project_root) / f"{slug}.md"
        if prop_path.exists():
            continue
        written.append(write_proposal(propose(pat), project_root))
    return written
