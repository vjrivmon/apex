# APEX Hub — Auditoría

**Fecha:** 2026-05-03
**Repo:** `~/RoadToDevOps/apex-hub/`
**Estado del repo:** v2 estable, MVP1-4 completados antes de 2026-04-30

## 0. Resumen ejecutivo

Hub v2 es **arquitectónicamente sólido**: FastAPI + SQLite WAL + FTS5 + SSE + frontend vanilla. MVP1 (drill-down + Cmd+K + live persistente), MVP2 (carpetas + clientes + tags), MVP3 (sync VPS + biblioteca UI), MVP4 (Telegram bot) están completados. El último commit (`f154e0c`) arregla hubs duplicados, sidebar counts y concurrencia.

**El gap crítico no es interno: es la integración con APEX.** El Hub está listo para recibir eventos del MCP server APEX, pero APEX nunca los envía. El Hub es un **receptor pasivo desconectado del emisor**.

---

## 1. Estado por capa

### 1.1 Backend (FastAPI · puerto auto-detect 3006+)

- 11 routers de endpoints (projects, errors, kb, search, palette, live, library, clients, folders, tags, design)
- WAL mode + threading.Lock en `get_db()` — concurrencia OK
- Auto-detect de puerto vía `~/.apex/hub-v2-port` y `~/.apex/hub-v2.pid` (evita duplicados)
- SSE en `/api/live/events` (timeline persistente)
- Watchdog daemon en `scanner_daemon/` que agrega `context.db` de todos los proyectos en `~/RoadToDevOps/*/.apex/`

### 1.2 Frontend (vanilla HTML/CSS/JS)

- 8 vistas: home, project detail, errors, kb, library, clients, live, palette
- CSS 1.471 líneas con design tokens (Figtree + IBM Plex Mono)
- Lucide SVG inline (sin emojis — alineado con regla absoluta #5 de APEX)
- Hashroute SPA (`#/project/{id}`) con dispatcher `render()`
- `marked.js` para markdown drill-down

### 1.3 Schema hub.db (14 tablas + FTS5)

```
projects · phases · errors · wiki_pages · decisions · components ·
session_logs · clients · folders · project_tags · ui_components ·
live_events · pending_sync · hub_search (FTS5)
```

11 índices. Esquema bien normalizado.

### 1.4 Mejoras recientes

```
f154e0c (HEAD) fix: hubs duplicados + sidebar counts + concurrencia + nuevos proyectos
fed2a6d feat: MVP2 carpetas+clientes+tags + briefing Telegram enriquecido
9ee54cd fix(telegram): cargar .env + sustituir guiones
be18f41 feat: MVP3 sync VPS + Biblioteca UI + MVP4 Telegram bot
88de101 Merge refactor/v2: cutover atómico
d3039e0 feat: MVP1 — Hub portado + drill-down + live persistente + Cmd+K
```

---

## 2. UX/UI gaps detectados (8)

| ID | Severidad | Gap |
|---|---|---|
| GAP-HUB-1 | CRIT | Sin ingesta real de eventos APEX. `/api/live/event` existe pero `_debug_log()` de APEX no lo llama. |
| GAP-HUB-2 | CRIT | `apex_search_cross_project` (MCP tool) no tiene endpoint en el Hub. Devuelve "offline". |
| GAP-HUB-3 | MED | Las **5 lecciones cross-project** que el `session-start.py` inyecta no se visualizan en el dashboard. El Hub tiene los datos pero no la vista. |
| GAP-HUB-4 | MED | Sin métricas en topbar: proyectos activos, errores críticos abiertos, fases en curso, tasa de actividad. |
| GAP-HUB-5 | MED | Sin vista de **skills disponibles**. Si APEX tiene 19 skills + las que se generen con meta-forge (S11), el Hub debería listarlas con tags filtrables. |
| GAP-HUB-6 | LOW | Estado `contract_end < hoy` en `clients` no tiene badge visual. |
| GAP-HUB-7 | LOW | Sin pagination/lazy-load en `/errors`, `/kb`, `/library` (cargan todo o top-N). |
| GAP-HUB-8 | LOW | Sidebar folder counts pueden desincronizarse con cambios concurrentes (parcialmente fixed en HEAD). |

---

## 3. Mejoras propuestas (priorizadas)

### Tier 1 — Sprint 8 (junto al Bridge APEX↔Hub)

1. **Conectar `_debug_log()` → `POST /api/live/event`**
   *(en el repo APEX, no en hub)*. Detección puerto desde `~/.apex/hub-v2-port`. Retry exponencial 1s/2s/4s. Timeout 2s. No bloquea.
2. **Endpoint `GET /api/hub/search-cross-project?q=X&limit=5`**
   Wrapper sobre `hub_search` FTS5 con filtros `source_type IN ('decision', 'error', 'lesson')`. Devuelve top-5 con score.
3. **Vista `/lessons` (5 lecciones críticas cross-project)**
   Renderiza las que `session-start.py` inyecta. Filtros por proyecto origen y severidad. Link a "ver proyecto".

### Tier 2 — Sprint 9-10 (con grader vivo)

4. **Widget "Grader feed" en home**
   Stream de verdicts del grader: fase, quality, should_block. Permite ver en vivo qué proyecto está atascado.
5. **Métricas en topbar**: 4 contadores (proyectos activos / errores críticos / fases en curso / verdicts hoy).
6. **Vista `/skills`** con tags y filtros por fase. Lee skills desde APEX repo (file system) o desde tabla `skills` nueva.

### Tier 3 — Sprint 11-13

7. **Browser-trace viewer**: cuando S11 capture sesiones, exponer en `/traces/{session_id}` con timeline interactivo (eventos CDP, screenshots, network).
8. **Apex-doctor digest** (S13): vista `/improvements` con clusters detectados de errores recurrentes cross-project.
9. **Lazy-load + pagination** universal.
10. **Dark mode toggle** (CSS variables ya soportan).

---

## 4. Integración APEX↔Hub: estado real

| Aspecto | Hoy | Lo que falta |
|---|---|---|
| `_debug_log()` payloads | NO se envían al Hub. Sólo a stdout/file. | Conectar al endpoint POST. |
| Endpoint ingesta | EXISTE (`/api/live/event`, persistente) | — |
| Cross-project search | NO implementado en Hub | Crear endpoint + cliente HTTP en MCP. |
| Inyección de lecciones en sesión | EXISTE (`session-start.py`) | El Hub no las visualiza, pero la inyección funciona. |
| Tabla destino | EXISTE (`live_events` + `hub_search`) | — |
| Hub-online check | NO se verifica al iniciar sesión APEX | Hook session-start: si Hub offline, `apex_add_error`. |

**Diagnóstico:** Hub v2 receptivo y bien diseñado, pero APEX nunca le habla. Tres líneas faltantes en `mcp/apex_server.py` cierran el 70% del gap.

---

## 5. Plan de remediación (incluido en Sprint 8.3)

S8.3.1 — Cliente HTTP en `apex_server.py::_debug_log()` con detección puerto + retry.
S8.3.2 — Endpoint `/api/hub/search-cross-project` en `apex-hub/backend/`.
S8.3.3 — Implementación real de `apex_search_cross_project` (hoy devuelve offline).
S8.3.4 — Hook `session-start.py` añade check de Hub vivo antes de inyectar lecciones.

**Definition of Done para Sprint 8.3:**
- Crear un proyecto piloto con `/apex` desde cero.
- Verificar en `/live` del Hub que cada `apex_*` tool emite evento.
- Llamar a `apex_search_cross_project("emojis")` y obtener la lección focusnow#2.

---

## 6. No-regresión recomendada

Los gaps internos del Hub (Tier 2-3) NO se atacan en Sprint 8. Razón: el Hub funciona. La urgencia es el bus de eventos roto, no la UI. Sprint 9-10 lo retoma cuando ya tengamos verdicts del grader fluyendo y haya algo real que visualizar en el dashboard.
