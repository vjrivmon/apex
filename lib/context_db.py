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
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

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

    # ── Convenience: get_full_context alias ──

    async def get_full_context(self) -> str:
        """Alias para get_context('full')."""
        return await self.get_context("full")
