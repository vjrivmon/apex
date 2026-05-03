"""APEX Context DB v2 — Persistencia inteligente de contexto para Claude Code.

Mejoras sobre v1:
- Temporal facts: decisiones con valid_at/invalid_at (patrón Graphiti)
- Progressive disclosure: 3 niveles de contexto (compact/timeline/full)
- LLM-Wiki integration: index.md + log.md por proyecto
- Dreaming-ready: scoring de señales para promoción a memoria permanente

Uso:
    db = ApexContextDB("/ruta/proyecto/.apex/context.db")
    await db.initialize()

    # Registrar decisión con temporalidad
    await db.add_decision("stack", "FastAPI + SQLite", "Backend-first",
                          phase=2, valid_from="2026-04-07")

    # Invalidar decisión anterior
    await db.invalidate_decision(decision_id, "Cambiamos a PostgreSQL")

    # Contexto progresivo (ahorra tokens)
    compact = await db.get_context("compact")   # ~200 tokens
    timeline = await db.get_context("timeline")  # ~800 tokens
    full = await db.get_context("full")          # ~2000 tokens
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


_WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """Split `text` into lowercase word tokens (unicode-aware)."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS project_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS phases (
    phase_number INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    started_at TEXT,
    completed_at TEXT,
    notes TEXT DEFAULT ''
);

-- Temporal facts: cada decisión tiene ventana de validez
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase INTEGER,
    category TEXT NOT NULL,
    decision TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    alternatives TEXT DEFAULT '',
    valid_from TEXT DEFAULT (datetime('now')),
    invalid_from TEXT,  -- NULL = sigue vigente
    superseded_by INTEGER REFERENCES decisions(id),
    created_at TEXT DEFAULT (datetime('now'))
);

-- Errores con scoring para dreaming/promoción
CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,  -- 'claude' | 'user'
    phase INTEGER,
    description TEXT NOT NULL,
    cause TEXT DEFAULT '',
    fix TEXT DEFAULT '',
    lesson TEXT DEFAULT '',
    severity TEXT DEFAULT 'medium',
    recurrence_count INTEGER DEFAULT 1,  -- cuántas veces se repitió
    last_seen TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT DEFAULT 'planned',
    phase INTEGER,
    description TEXT DEFAULT '',
    dependencies TEXT DEFAULT '[]',
    files TEXT DEFAULT '[]',
    tests TEXT DEFAULT '[]',
    last_modified TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS next_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    priority INTEGER DEFAULT 5,
    description TEXT NOT NULL,
    phase INTEGER,
    blocked_by TEXT DEFAULT '[]',
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS context_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date TEXT DEFAULT (date('now')),
    phase INTEGER,
    summary TEXT NOT NULL,
    key_outcomes TEXT DEFAULT '',
    tokens_used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS context_fts USING fts5(
    content, source, source_id
);

-- Dreaming system: log of light/deep/forget cycles
CREATE TABLE IF NOT EXISTS dreaming_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase TEXT NOT NULL,  -- 'light', 'deep', 'forget'
    candidates_count INTEGER,
    promoted_count INTEGER,
    archived_count INTEGER,
    details TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

-- Wiki entries: páginas del knowledge base del proyecto
CREATE TABLE IF NOT EXISTS wiki_pages (
    slug TEXT PRIMARY KEY,  -- ej: 'entities/product', 'concepts/price-normalization'
    title TEXT NOT NULL,
    content TEXT NOT NULL,  -- Markdown
    page_type TEXT DEFAULT 'entity',  -- entity, concept, comparison, query, raw
    tags TEXT DEFAULT '[]',  -- JSON array
    wikilinks TEXT DEFAULT '[]',  -- JSON array de slugs referenciados
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Grader verdicts: evaluación outcome-based al cerrar una fase (Sprint 8)
CREATE TABLE IF NOT EXISTS grader_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phase INTEGER NOT NULL,
    quality INTEGER NOT NULL,  -- 1=poor, 2=acceptable, 3=good, 4=excellent
    category TEXT,             -- coding, design, integration, deploy, ...
    issues TEXT DEFAULT '[]',  -- JSON array: ["mock_data", "no_git_init", ...]
    should_block INTEGER DEFAULT 0,  -- 1 = bloquea apex_set_phase
    reasoning TEXT NOT NULL,
    evidence_hash TEXT,        -- sha1 del evidence usado (idempotencia)
    deterministic_checks TEXT DEFAULT '{}',  -- JSON con {check_name: pass|fail}
    llm_judged INTEGER DEFAULT 0,  -- 1 si hubo evaluación LLM además de determinista
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_grader_phase ON grader_verdicts(phase, created_at DESC);
"""

PHASES = [
    (0, "socrático"), (1, "tipo_solución"), (2, "diseño"), (3, "spec"),
    (4, "edge_cases"), (5, "scaffold"), (6, "core"), (7, "infraestructura"),
    (8, "integración"), (9, "testing"), (10, "seguridad"), (11, "deploy"),
    (12, "iteración"), (13, "escalado"), (14, "mantenimiento"),
]


class ApexContextDB:

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._initialized = False

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self.db_path)) as db:
            await db.executescript(_SCHEMA)
            for num, name in PHASES:
                await db.execute(
                    "INSERT OR IGNORE INTO phases (phase_number, name) VALUES (?, ?)",
                    (num, name),
                )
            await db.commit()
        self._initialized = True

    def _conn(self) -> aiosqlite.Connection:
        return aiosqlite.connect(str(self.db_path))

    # ── Meta ──

    async def set_meta(self, key: str, value: str) -> None:
        async with self._conn() as db:
            await db.execute(
                "INSERT OR REPLACE INTO project_meta (key, value, updated_at) "
                "VALUES (?, ?, datetime('now'))", (key, value))
            await db.commit()

    async def get_meta(self, key: str) -> str | None:
        async with self._conn() as db:
            r = await db.execute_fetchall(
                "SELECT value FROM project_meta WHERE key = ?", (key,))
            return r[0][0] if r else None

    # ── Phases ──

    async def set_phase(self, num: int, status: str, notes: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        async with self._conn() as db:
            if status == "in_progress":
                await db.execute(
                    "UPDATE phases SET status=?, started_at=?, notes=? WHERE phase_number=?",
                    (status, now, notes, num))
            elif status == "completed":
                await db.execute(
                    "UPDATE phases SET status=?, completed_at=?, notes=? WHERE phase_number=?",
                    (status, now, notes, num))
            else:
                await db.execute(
                    "UPDATE phases SET status=?, notes=? WHERE phase_number=?",
                    (status, notes, num))
            await db.commit()

    async def get_current_phase(self) -> dict | None:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT phase_number, name, status, started_at, notes "
                "FROM phases WHERE status='in_progress' ORDER BY phase_number LIMIT 1")
            if rows:
                r = rows[0]
                return {"number": r[0], "name": r[1], "status": r[2],
                        "started_at": r[3], "notes": r[4]}
        return None

    async def get_all_phases(self) -> list[dict]:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT phase_number, name, status, started_at, completed_at, notes "
                "FROM phases ORDER BY phase_number")
        return [{"number": r[0], "name": r[1], "status": r[2],
                 "started_at": r[3], "completed_at": r[4], "notes": r[5]} for r in rows]

    # ── Decisions (temporal facts) ──

    async def add_decision(
        self, category: str, decision: str, reasoning: str,
        phase: int | None = None, alternatives: str = "",
        valid_from: str | None = None,
    ) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO decisions (phase, category, decision, reasoning, alternatives, valid_from) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (phase, category, decision, reasoning, alternatives,
                 valid_from or datetime.now(timezone.utc).isoformat()))
            await db.commit()
            rid = cur.lastrowid
            await self._index_fts(db, f"{decision}\n{reasoning}", "decision", rid)
            return rid

    async def invalidate_decision(self, decision_id: int, reason: str = "",
                                   superseded_by: int | None = None) -> None:
        """Marca una decisión como ya no vigente (temporal fact)."""
        async with self._conn() as db:
            await db.execute(
                "UPDATE decisions SET invalid_from=datetime('now'), superseded_by=? WHERE id=?",
                (superseded_by, decision_id))
            # Registrar en log (no en errors, para evitar nested connection)
            if reason:
                await db.execute(
                    "INSERT INTO context_log (phase, summary, key_outcomes) "
                    "VALUES (NULL, ?, ?)",
                    (f"Decisión #{decision_id} invalidada", reason))
            await db.commit()

    async def get_active_decisions(self, category: str | None = None) -> list[dict]:
        """Solo decisiones vigentes (invalid_from IS NULL)."""
        async with self._conn() as db:
            q = ("SELECT id, phase, category, decision, reasoning, alternatives, "
                 "valid_from, created_at FROM decisions WHERE invalid_from IS NULL")
            params = []
            if category:
                q += " AND category = ?"
                params.append(category)
            q += " ORDER BY created_at"
            rows = await db.execute_fetchall(q, params)
        return [{"id": r[0], "phase": r[1], "category": r[2], "decision": r[3],
                 "reasoning": r[4], "alternatives": r[5], "valid_from": r[6],
                 "created_at": r[7]} for r in rows]

    # ── Errors (con recurrencia) ──

    async def add_error(
        self, source: str, description: str, lesson: str,
        phase: int | None = None, cause: str = "", fix: str = "",
        severity: str = "medium",
    ) -> int:
        async with self._conn() as db:
            # Comprobar si ya existe un error similar (incrementar recurrence)
            existing = await db.execute_fetchall(
                "SELECT id, recurrence_count FROM errors "
                "WHERE source=? AND description=? LIMIT 1",
                (source, description))
            if existing:
                eid, count = existing[0]
                await db.execute(
                    "UPDATE errors SET recurrence_count=?, last_seen=datetime('now'), "
                    "lesson=? WHERE id=?",
                    (count + 1, lesson, eid))
                await db.commit()
                return eid
            cur = await db.execute(
                "INSERT INTO errors (source, phase, description, cause, fix, lesson, severity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, phase, description, cause, fix, lesson, severity))
            await db.commit()
            rid = cur.lastrowid
            await self._index_fts(db, f"{description}\n{lesson}", "error", rid)
            return rid

    async def get_errors(self, source: str | None = None, min_severity: str | None = None) -> list[dict]:
        async with self._conn() as db:
            q = "SELECT id, source, phase, description, cause, fix, lesson, severity, recurrence_count, last_seen FROM errors"
            conditions, params = [], []
            if source:
                conditions.append("source = ?")
                params.append(source)
            if min_severity:
                sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
                threshold = sev_order.get(min_severity, 2)
                valid = [s for s, v in sev_order.items() if v <= threshold]
                placeholders = ",".join("?" * len(valid))
                conditions.append(f"severity IN ({placeholders})")
                params.extend(valid)
            if conditions:
                q += " WHERE " + " AND ".join(conditions)
            q += " ORDER BY recurrence_count DESC, created_at DESC"
            rows = await db.execute_fetchall(q, params)
        return [{"id": r[0], "source": r[1], "phase": r[2], "description": r[3],
                 "cause": r[4], "fix": r[5], "lesson": r[6], "severity": r[7],
                 "recurrence_count": r[8], "last_seen": r[9]} for r in rows]

    # ── Components ──

    async def add_component(self, id: str, name: str, type: str,
                            phase: int | None = None, description: str = "",
                            dependencies: list[str] | None = None,
                            files: list[str] | None = None) -> None:
        async with self._conn() as db:
            await db.execute(
                "INSERT OR REPLACE INTO components "
                "(id, name, type, phase, description, dependencies, files, last_modified) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (id, name, type, phase, description,
                 json.dumps(dependencies or []), json.dumps(files or [])))
            await db.commit()
            await self._index_fts(db, f"{name}\n{description}", "component", id)

    async def update_component_status(self, id: str, status: str) -> None:
        async with self._conn() as db:
            await db.execute(
                "UPDATE components SET status=?, last_modified=datetime('now') WHERE id=?",
                (status, id))
            await db.commit()

    async def get_components(self, type: str | None = None, status: str | None = None) -> list[dict]:
        async with self._conn() as db:
            q = "SELECT id, name, type, status, phase, description, dependencies, files FROM components"
            conds, params = [], []
            if type:
                conds.append("type=?"); params.append(type)
            if status:
                conds.append("status=?"); params.append(status)
            if conds:
                q += " WHERE " + " AND ".join(conds)
            q += " ORDER BY phase, name"
            rows = await db.execute_fetchall(q, params)
        return [{"id": r[0], "name": r[1], "type": r[2], "status": r[3],
                 "phase": r[4], "description": r[5],
                 "dependencies": json.loads(r[6]), "files": json.loads(r[7])} for r in rows]

    # ── Next Steps ──

    async def add_next_step(self, description: str, priority: int = 5,
                            phase: int | None = None,
                            blocked_by: list[str] | None = None) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO next_steps (priority, description, phase, blocked_by) "
                "VALUES (?, ?, ?, ?)",
                (priority, description, phase, json.dumps(blocked_by or [])))
            await db.commit()
            return cur.lastrowid

    async def complete_step(self, step_id: int) -> None:
        async with self._conn() as db:
            await db.execute("UPDATE next_steps SET status='done' WHERE id=?", (step_id,))
            await db.commit()

    async def get_next_steps(self, status: str = "pending") -> list[dict]:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT id, priority, description, phase, blocked_by, status "
                "FROM next_steps WHERE status=? ORDER BY priority", (status,))
        return [{"id": r[0], "priority": r[1], "description": r[2],
                 "phase": r[3], "blocked_by": json.loads(r[4]), "status": r[5]} for r in rows]

    # ── Context Log ──

    async def log_session(self, summary: str, key_outcomes: str = "",
                          phase: int | None = None) -> None:
        async with self._conn() as db:
            await db.execute(
                "INSERT INTO context_log (phase, summary, key_outcomes) VALUES (?, ?, ?)",
                (phase, summary, key_outcomes))
            await db.commit()

    # ── Wiki Pages ──

    async def add_wiki_page(self, slug: str, title: str, content: str,
                            page_type: str = "entity", tags: list[str] | None = None,
                            wikilinks: list[str] | None = None) -> None:
        async with self._conn() as db:
            await db.execute(
                "INSERT OR REPLACE INTO wiki_pages "
                "(slug, title, content, page_type, tags, wikilinks, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (slug, title, content, page_type,
                 json.dumps(tags or []), json.dumps(wikilinks or [])))
            await db.commit()
            await self._index_fts(db, f"{title}\n{content}", "wiki", slug)

    async def get_wiki_page(self, slug: str) -> dict | None:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT slug, title, content, page_type, tags, wikilinks "
                "FROM wiki_pages WHERE slug=?", (slug,))
            if rows:
                r = rows[0]
                return {"slug": r[0], "title": r[1], "content": r[2],
                        "type": r[3], "tags": json.loads(r[4]),
                        "wikilinks": json.loads(r[5])}
        return None

    async def list_wiki_pages(self, page_type: str | None = None) -> list[dict]:
        async with self._conn() as db:
            if page_type:
                rows = await db.execute_fetchall(
                    "SELECT slug, title, page_type, tags FROM wiki_pages WHERE page_type=?",
                    (page_type,))
            else:
                rows = await db.execute_fetchall(
                    "SELECT slug, title, page_type, tags FROM wiki_pages ORDER BY slug")
        return [{"slug": r[0], "title": r[1], "type": r[2],
                 "tags": json.loads(r[3])} for r in rows]

    # ── Search ──

    async def search(self, query: str, limit: int = 10) -> list[dict]:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT content, source, source_id FROM context_fts "
                "WHERE context_fts MATCH ? LIMIT ?", (query, limit))
        return [{"content": r[0], "source": r[1], "source_id": r[2]} for r in rows]

    async def search_hybrid(self, query: str, limit: int = 10,
                             fts_weight: float = 0.7,
                             kw_weight: float = 0.3) -> list[dict]:
        """Búsqueda híbrida: 70% FTS5 BM25 + 30% keyword overlap.

        Motivación: FTS5 solo no encuentra queries con typos o términos
        inflectados ("lecciones" no matchea "lección"). Combinar con
        keyword LIKE amplía el recall sin perder precision — el ranking
        final pondera ambas fuentes con `fts_weight` y `kw_weight`.

        Estrategia:
        1. FTS5 devuelve candidatos con su rank (negativo; menor = mejor).
        2. Por cada token del query (len ≥ 3), añadir candidatos adicionales
           con LIKE. Cada fila gana un punto por token matched.
        3. Normalizar ambos scores a [0, 1] y combinar.
        4. Ordenar descendente por hybrid_score.
        """
        if not query.strip():
            return []

        tokens = [t for t in _tokenize(query) if len(t) >= 3]
        if not tokens:
            return await self.search(query, limit=limit)

        # --- 1. FTS5 candidatos ---
        try:
            async with self._conn() as db:
                fts_rows = await db.execute_fetchall(
                    "SELECT content, source, source_id, rank FROM context_fts "
                    "WHERE context_fts MATCH ? ORDER BY rank LIMIT ?",
                    (query, max(limit * 3, 20)),
                )
        except Exception:
            fts_rows = []

        # --- 2. Keyword candidatos (LIKE) ---
        kw_candidates: dict[tuple, dict] = {}
        async with self._conn() as db:
            for token in tokens:
                pattern = f"%{token}%"
                rows = await db.execute_fetchall(
                    "SELECT content, source, source_id FROM context_fts "
                    "WHERE content LIKE ? LIMIT ?",
                    (pattern, max(limit * 2, 20)),
                )
                for content, source, source_id in rows:
                    key = (source, source_id)
                    entry = kw_candidates.setdefault(key, {
                        "content": content, "source": source,
                        "source_id": source_id, "kw_matches": 0,
                    })
                    entry["kw_matches"] += 1

        # --- 3. Merge + scoring ---
        merged: dict[tuple, dict] = {}
        fts_ranks = [r[3] for r in fts_rows if r[3] is not None]
        # Normalizar FTS: rank es negativo (BM25), más bajo = mejor
        if fts_ranks:
            min_r, max_r = min(fts_ranks), max(fts_ranks)
            span = max_r - min_r or 1.0
        else:
            min_r = max_r = 0
            span = 1.0

        for content, source, source_id, rank in fts_rows:
            key = (source, source_id)
            fts_norm = 0.0
            if rank is not None:
                # rank más bajo → fts_norm más alto
                fts_norm = (max_r - rank) / span
            merged[key] = {
                "content": content, "source": source, "source_id": source_id,
                "fts_score": fts_norm, "kw_matches": 0,
            }

        for key, kw in kw_candidates.items():
            if key in merged:
                merged[key]["kw_matches"] = kw["kw_matches"]
            else:
                merged[key] = {
                    "content": kw["content"], "source": kw["source"],
                    "source_id": kw["source_id"],
                    "fts_score": 0.0, "kw_matches": kw["kw_matches"],
                }

        if not merged:
            return []

        max_kw = max(m["kw_matches"] for m in merged.values()) or 1
        results = []
        for m in merged.values():
            kw_norm = m["kw_matches"] / max_kw
            m["hybrid_score"] = fts_weight * m["fts_score"] + kw_weight * kw_norm
            results.append(m)

        results.sort(key=lambda r: r["hybrid_score"], reverse=True)
        return results[:limit]

    # ── Progressive Disclosure (3 niveles) ──

    async def get_context(self, level: str = "compact") -> str:
        """Genera contexto en 3 niveles para optimizar tokens.

        - compact:  ~200 tokens. Fase actual, meta, próximos pasos. Para agentes rápidos.
        - timeline: ~800 tokens. + decisiones activas, errores recurrentes, componentes.
        - full:     ~2000 tokens. + wiki index, context logs, todos los detalles.
        """
        if level == "compact":
            return await self._context_compact()
        elif level == "timeline":
            return await self._context_timeline()
        else:
            return await self._context_full()

    async def _context_compact(self) -> str:
        """Nivel compacto: fase + meta + próximos pasos (~200 tokens)."""
        lines = ["# APEX Context (compact)"]
        async with self._conn() as db:
            meta = await db.execute_fetchall("SELECT key, value FROM project_meta")
        for k, v in meta:
            lines.append(f"- {k}: {v}")

        current = await self.get_current_phase()
        if current:
            lines.append(f"\n**Fase actual**: {current['number']} — {current['name']}")
            if current["notes"]:
                lines.append(f"  {current['notes']}")

        steps = await self.get_next_steps()
        if steps:
            lines.append("\n**Próximos pasos**:")
            for s in steps[:3]:
                lines.append(f"- [P{s['priority']}] {s['description']}")

        return "\n".join(lines)

    async def _context_timeline(self) -> str:
        """Nivel timeline: + decisiones + errores + componentes (~800 tokens)."""
        lines = [await self._context_compact(), "\n---"]

        decisions = await self.get_active_decisions()
        if decisions:
            lines.append("\n## Decisiones vigentes")
            for d in decisions[-8:]:
                lines.append(f"- **{d['category']}**: {d['decision']}")

        errors = await self.get_errors()
        # Solo errores recurrentes o de alta severidad
        important = [e for e in errors if e["recurrence_count"] > 1 or e["severity"] in ("high", "critical")]
        if important:
            lines.append("\n## Errores a evitar")
            for e in important[:5]:
                times = f" (x{e['recurrence_count']})" if e["recurrence_count"] > 1 else ""
                lines.append(f"- [{e['source']}] {e['description']}{times}")
                if e["lesson"]:
                    lines.append(f"  → {e['lesson']}")

        components = await self.get_components()
        if components:
            lines.append("\n## Componentes")
            icons = {"planned": "⬜", "in_progress": "🔨", "implemented": "✅",
                     "tested": "🧪", "verified": "✓"}
            for c in components:
                lines.append(f"- {icons.get(c['status'], '?')} {c['name']} ({c['type']})")

        return "\n".join(lines)

    async def _context_full(self) -> str:
        """Nivel completo: + wiki index + logs + todas las fases (~2000 tokens)."""
        lines = [await self._context_timeline(), "\n---"]

        # Todas las fases
        phases = await self.get_all_phases()
        completed = [p for p in phases if p["status"] == "completed"]
        if completed:
            lines.append("\n## Fases completadas")
            for p in completed:
                lines.append(f"- [x] {p['number']}: {p['name']}")

        # Wiki pages index
        pages = await self.list_wiki_pages()
        if pages:
            lines.append("\n## Knowledge Base")
            for p in pages:
                lines.append(f"- [[{p['slug']}]] — {p['title']}")

        # Recent context logs
        async with self._conn() as db:
            logs = await db.execute_fetchall(
                "SELECT session_date, summary, key_outcomes FROM context_log "
                "ORDER BY created_at DESC LIMIT 5")
        if logs:
            lines.append("\n## Sesiones recientes")
            for date, summary, outcomes in logs:
                lines.append(f"- **{date}**: {summary}")
                if outcomes:
                    lines.append(f"  Resultados: {outcomes}")

        # Todas las decisiones (incluyendo invalidadas)
        async with self._conn() as db:
            all_decisions = await db.execute_fetchall(
                "SELECT category, decision, invalid_from FROM decisions ORDER BY created_at")
        invalidated = [d for d in all_decisions if d[2]]
        if invalidated:
            lines.append("\n## Decisiones invalidadas (historial)")
            for cat, dec, inv in invalidated:
                lines.append(f"- ~~{cat}: {dec}~~ (invalidada {inv})")

        return "\n".join(lines)

    # ── Dreaming System ──
    # Inspired by OpenClaw: promotes short-term signals to permanent memory.
    # Three phases: light (collect candidates), deep (score & promote), forget (archive stale).

    _SIGNAL_WEIGHTS = {
        "frequency": 0.24,
        "recurrence": 0.30,
        "severity": 0.15,
        "recency": 0.15,
        "phase_relevance": 0.16,
    }

    _SEVERITY_SCORES = {
        "critical": 1.0,
        "high": 0.8,
        "medium": 0.5,
        "low": 0.2,
    }

    async def dream_light(self) -> list[dict]:
        """Light phase: collect recent signals, dedupe, stage candidates for promotion.

        Looks at decisions, errors, and components from the last 24 hours.
        Scores each candidate by frequency, recurrence_count, and severity.
        Returns candidates with preliminary scores.
        """
        candidates: list[dict] = []
        async with self._conn() as db:
            # Recent decisions (last 24h)
            rows = await db.execute_fetchall(
                "SELECT id, category, decision, reasoning, phase "
                "FROM decisions "
                "WHERE created_at >= datetime('now', '-1 day') "
                "  AND invalid_from IS NULL "
                "ORDER BY created_at DESC"
            )
            # Count decisions per category for frequency scoring
            cat_counts: dict[str, int] = {}
            for r in rows:
                cat_counts[r[1]] = cat_counts.get(r[1], 0) + 1
            for r in rows:
                freq = min(cat_counts[r[1]] / max(len(rows), 1), 1.0)
                candidates.append({
                    "source": "decision",
                    "source_id": r[0],
                    "category": r[1],
                    "content": r[2],
                    "reasoning": r[3],
                    "phase": r[4],
                    "frequency": freq,
                    "recurrence": 0.0,
                    "severity": 0.5,  # neutral for decisions
                    "score": 0.0,  # computed in dream_deep
                })

            # Recent errors (last 24h)
            rows = await db.execute_fetchall(
                "SELECT id, description, lesson, severity, recurrence_count, phase "
                "FROM errors "
                "WHERE last_seen >= datetime('now', '-1 day') "
                "ORDER BY recurrence_count DESC"
            )
            total_errors = max(len(rows), 1)
            for r in rows:
                recurrence = min(r[4] / 5.0, 1.0)  # cap at 5 occurrences = 1.0
                sev_score = self._SEVERITY_SCORES.get(r[3], 0.5)
                candidates.append({
                    "source": "error",
                    "source_id": r[0],
                    "category": r[3],
                    "content": r[1],
                    "reasoning": r[2],
                    "phase": r[5],
                    "frequency": min(r[4] / total_errors, 1.0),
                    "recurrence": recurrence,
                    "severity": sev_score,
                    "score": 0.0,
                })

            # Recently modified components (last 24h)
            rows = await db.execute_fetchall(
                "SELECT id, name, type, status, phase, description "
                "FROM components "
                "WHERE last_modified >= datetime('now', '-1 day') "
                "ORDER BY last_modified DESC"
            )
            for r in rows:
                status_score = {"implemented": 0.7, "tested": 0.9, "verified": 1.0,
                                "in_progress": 0.4, "planned": 0.2}.get(r[3], 0.3)
                candidates.append({
                    "source": "component",
                    "source_id": r[0],
                    "category": r[2],
                    "content": r[1],
                    "reasoning": r[5],
                    "phase": r[4],
                    "frequency": 0.5,
                    "recurrence": 0.0,
                    "severity": status_score,
                    "score": 0.0,
                })

            # Dedupe: keep highest-scoring candidate per (source, content)
            seen: dict[tuple[str, str], int] = {}
            deduped: list[dict] = []
            for c in candidates:
                key = (c["source"], c["content"])
                if key in seen:
                    idx = seen[key]
                    # Merge: bump frequency for duplicates
                    deduped[idx]["frequency"] = min(deduped[idx]["frequency"] + 0.2, 1.0)
                else:
                    seen[key] = len(deduped)
                    deduped.append(c)

            # Log the light phase
            await db.execute(
                "INSERT INTO dreaming_log (phase, candidates_count, promoted_count, "
                "archived_count, details) VALUES (?, ?, ?, ?, ?)",
                ("light", len(deduped), 0, 0,
                 f"Sources: {len([c for c in deduped if c['source'] == 'decision'])} decisions, "
                 f"{len([c for c in deduped if c['source'] == 'error'])} errors, "
                 f"{len([c for c in deduped if c['source'] == 'component'])} components"))
            await db.commit()

        return deduped

    async def dream_deep(self, min_score: float = 0.6) -> list[dict]:
        """Deep phase: score candidates and promote above threshold to permanent wiki.

        Scoring weights:
        - Frequency (0.24): how often this signal appeared
        - Recurrence (0.30): how many times an error recurred
        - Severity (0.15): critical > high > medium > low
        - Recency (0.15): how recently the signal was seen
        - Phase relevance (0.16): matches current phase = higher score

        Candidates above min_score are promoted to wiki pages.
        Returns list of promoted items.
        """
        candidates = await self.dream_light()
        if not candidates:
            return []

        current_phase = await self.get_current_phase()
        current_phase_num = current_phase["number"] if current_phase else 0

        # Score all candidates
        for c in candidates:
            # Recency: 1.0 if today, decays. Since dream_light already filters
            # to last 24h, all candidates are recent by definition.
            recency = 1.0

            # Phase relevance: higher if candidate phase matches current
            phase_relevance = 0.5  # default
            if c["phase"] is not None:
                diff = abs(c["phase"] - current_phase_num)
                if diff == 0:
                    phase_relevance = 1.0
                elif diff <= 2:
                    phase_relevance = 0.7
                else:
                    phase_relevance = 0.3

            w = self._SIGNAL_WEIGHTS
            c["score"] = (
                w["frequency"] * c["frequency"]
                + w["recurrence"] * c["recurrence"]
                + w["severity"] * c["severity"]
                + w["recency"] * recency
                + w["phase_relevance"] * phase_relevance
            )

        # Filter and promote
        promoted: list[dict] = []
        async with self._conn() as db:
            for c in candidates:
                if c["score"] < min_score:
                    continue

                # Build wiki page from candidate
                slug = f"dreaming/{c['source']}/{c['source_id']}"
                title = f"[{c['source'].upper()}] {c['content'][:80]}"

                content_parts = [
                    f"# {title}\n",
                    f"**Source**: {c['source']} (id: {c['source_id']})",
                    f"**Category**: {c['category']}",
                    f"**Phase**: {c['phase']}",
                    f"**Dream Score**: {c['score']:.2f}",
                    f"**Promoted**: {datetime.now(timezone.utc).isoformat()}\n",
                    f"## Content\n\n{c['content']}\n",
                ]
                if c["reasoning"]:
                    content_parts.append(f"## Reasoning\n\n{c['reasoning']}\n")

                wiki_content = "\n".join(content_parts)

                await db.execute(
                    "INSERT OR REPLACE INTO wiki_pages "
                    "(slug, title, content, page_type, tags, wikilinks, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                    (slug, title, wiki_content, "dreaming",
                     json.dumps([c["source"], c["category"]]),
                     json.dumps([])))

                promoted.append(c)

            # Log the deep phase
            await db.execute(
                "INSERT INTO dreaming_log (phase, candidates_count, promoted_count, "
                "archived_count, details) VALUES (?, ?, ?, ?, ?)",
                ("deep", len(candidates), len(promoted), 0,
                 f"min_score={min_score}, scores={[round(c['score'], 2) for c in candidates]}"))
            await db.commit()

        return promoted

    async def dream_forget(self, max_age_days: int = 30) -> int:
        """Archive old, low-relevance context_log entries.

        Marks entries older than max_age_days as archived by setting a
        key_outcomes prefix. Does not delete data -- just marks it so
        progressive disclosure can filter it out.

        Returns count of archived entries.
        """
        async with self._conn() as db:
            # Find old context_log entries that haven't been archived yet
            rows = await db.execute_fetchall(
                "SELECT id FROM context_log "
                "WHERE created_at < datetime('now', ? || ' days') "
                "  AND key_outcomes NOT LIKE '[ARCHIVED]%'",
                (f"-{max_age_days}",))

            archived_count = len(rows)
            if archived_count > 0:
                ids = [r[0] for r in rows]
                placeholders = ",".join("?" * len(ids))
                await db.execute(
                    f"UPDATE context_log SET key_outcomes = '[ARCHIVED] ' || key_outcomes "
                    f"WHERE id IN ({placeholders})",
                    ids)

            # Also archive old dreaming wiki pages (older than max_age_days)
            # that have low scores (below 0.5 in their content)
            old_wiki = await db.execute_fetchall(
                "SELECT slug FROM wiki_pages "
                "WHERE page_type = 'dreaming' "
                "  AND updated_at < datetime('now', ? || ' days')",
                (f"-{max_age_days}",))

            wiki_archived = 0
            for (slug,) in old_wiki:
                # Re-tag as archived rather than deleting
                await db.execute(
                    "UPDATE wiki_pages SET page_type = 'dreaming_archived' "
                    "WHERE slug = ?", (slug,))
                wiki_archived += 1

            total_archived = archived_count + wiki_archived

            # Log the forget phase
            await db.execute(
                "INSERT INTO dreaming_log (phase, candidates_count, promoted_count, "
                "archived_count, details) VALUES (?, ?, ?, ?, ?)",
                ("forget", 0, 0, total_archived,
                 f"max_age_days={max_age_days}, "
                 f"context_log={archived_count}, wiki_pages={wiki_archived}"))
            await db.commit()

        return total_archived

    # ── Helpers ──

    async def _index_fts(self, db: aiosqlite.Connection, content: str,
                         source: str, source_id) -> None:
        try:
            await db.execute(
                "INSERT INTO context_fts (content, source, source_id) VALUES (?, ?, ?)",
                (content, source, str(source_id) if source_id else ""))
            await db.commit()
        except Exception:
            pass

    # ── Grader verdicts (Sprint 8) ──

    async def add_verdict(
        self,
        phase: int,
        quality: int,
        reasoning: str,
        category: str | None = None,
        issues: list[str] | None = None,
        should_block: bool = False,
        evidence_hash: str | None = None,
        deterministic_checks: dict | None = None,
        llm_judged: bool = False,
    ) -> int:
        import json as _json
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO grader_verdicts (phase, quality, category, issues, "
                "should_block, reasoning, evidence_hash, deterministic_checks, llm_judged) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (phase, quality, category, _json.dumps(issues or []),
                 1 if should_block else 0, reasoning, evidence_hash,
                 _json.dumps(deterministic_checks or {}), 1 if llm_judged else 0))
            await db.commit()
            return cur.lastrowid

    async def get_latest_verdict(self, phase: int) -> dict | None:
        import json as _json
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT id, phase, quality, category, issues, should_block, "
                "reasoning, evidence_hash, deterministic_checks, llm_judged, created_at "
                "FROM grader_verdicts WHERE phase=? ORDER BY created_at DESC LIMIT 1",
                (phase,))
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r[0], "phase": r[1], "quality": r[2], "category": r[3],
            "issues": _json.loads(r[4] or "[]"),
            "should_block": bool(r[5]), "reasoning": r[6],
            "evidence_hash": r[7],
            "deterministic_checks": _json.loads(r[8] or "{}"),
            "llm_judged": bool(r[9]), "created_at": r[10],
        }

    async def list_verdicts(self, limit: int = 20) -> list[dict]:
        import json as _json
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT id, phase, quality, category, issues, should_block, "
                "reasoning, llm_judged, created_at FROM grader_verdicts "
                "ORDER BY created_at DESC LIMIT ?", (limit,))
        return [{
            "id": r[0], "phase": r[1], "quality": r[2], "category": r[3],
            "issues": _json.loads(r[4] or "[]"),
            "should_block": bool(r[5]), "reasoning": r[6],
            "llm_judged": bool(r[7]), "created_at": r[8],
        } for r in rows]

    # ── Convenience: get_full_context alias ──

    async def get_full_context(self) -> str:
        """Alias para get_context('full')."""
        return await self.get_context("full")
