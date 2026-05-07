# Blueprint S17 + S18 — VirtualFS cross-project + Granite Curator opcional

> Generado en sesión `868a7915-4dc` (2026-05-07). Referenciado desde S15 blueprint.
> Orden de ejecución: **S15.A** (cerrado) → **S15.B** (en marcha) → **S16** (maduración Advisor con datos reales, ya anclado en S15) → **S17** → **S18**.
>
> Ambos sprints son **independientes**: S17 entrega valor sin S18 y viceversa. S17 primero porque da el playground sobre el que S18 puede curar.

---

## Contexto compartido — el problema real

Vicente tiene **11 proyectos en `~/RoadToDevOps/`** + ApexVault (Obsidian) + apex-hub. Cada uno con su `.apex/context.db`, `wiki/`, `.apex/raw/`, `.apex/handoff/`. Hoy un agente trabajando en `apex` no puede recorrer los demás sin pagar contexto enorme: `apex_search_cross_project` devuelve chunks BM25 (top-K), no permite *navegación* tipo `cd`/`ls`/`cat`/`grep -r`.

Paralelamente, APEX mantiene contexto **a mano** con heurísticas (`lib/token_filter.py` corta por chars, `lib/handoff.py` plantilla fija, `context-watch.py` umbral 200K absoluto). Eso funciona pero es ciego al contenido — un modelo pequeño local especializado lo haría mejor sin tocar el coste marginal.

S17 ataca el primer dolor (navegación cross-project). S18 ataca el segundo (curado de contexto) y lo hace **opt-in con env**, sin convertirse en dependencia dura.

---

# Sprint 17 — VirtualFS cross-project read-only

## 1. Goal

Un mount lógico read-only que un agente APEX en cualquier proyecto pueda recorrer con primitivas UNIX para encontrar lecciones, decisiones, handoffs y errores en otros proyectos del ecosistema, sin gastar tokens en `apex_search_cross_project` repetidos.

## 2. Layout del filesystem virtual

```
/projects/<slug>/wiki/                ← mount real RO de <root>/<slug>/wiki/
/projects/<slug>/decisions/           ← mount real RO de <root>/<slug>/wiki/decisions/
/projects/<slug>/handoffs/            ← mount real RO de <root>/<slug>/.apex/handoff/
/projects/<slug>/raw/                 ← mount real RO de <root>/<slug>/.apex/raw/
/projects/<slug>/errors/              ← virtualizado desde <slug>/.apex/context.db (errors)
/projects/<slug>/skills-history/      ← virtualizado desde role_invocations + grader_verdicts
/lessons/critical/                    ← virtualizado desde hub.db (cross_project_lessons)
/lessons/by-project/<slug>.md         ← agregado por proyecto
/vault/                               ← mount real RO de ApexVault path
```

**80% son mounts reales**: solo necesitan path mapping. **20% son materializaciones SQL→markdown** que se generan on-demand y se cachean por hash.

## 3. Implementación

- `lib/vfs.py` (~350L): clase `VirtualFS` con métodos `ls(path)`, `cat(path)`, `grep(pattern, path, flags)`, `find(path, name=None)`. Path resolver con whitelist en `hub.db.global_meta.vfs_allowed_roots` (default: `~/RoadToDevOps`, ApexVault path).
- `lib/vfs_sql_render.py` (~200L): renderizadores `errors_to_md(slug)`, `skills_history_to_md(slug)`, `lessons_to_md(severity)`. Cachea en `vfs_render_cache` (key = sha256(query+rows)).
- `lib/vfs_grep.py` (~150L): traducción de flags grep (`-i`, `-r`, `-n`, `-l`, `-E`) usando `shlex` + handler manual. **Pre-filtro FTS5** antes del grep fino: el FTS5 de cada `context.db` da candidatos, grep filtra in-memory.
- **Read-only enforced**: cualquier write devuelve `EROFS` (patrón Mintlify). Sin sesiones, sin estado.

## 4. Tools MCP nuevas (4)

- `apex_vfs_exec(command: str)` — ejecuta una línea bash limitada (`ls`/`cat`/`grep`/`find` solo). Devuelve `{stdout, stderr, exit_code}`. **Tool universal**, equivale al `Bash` de Claude pero scoped al VFS.
- `apex_vfs_ls(path)` — typed alternative para casos comunes.
- `apex_vfs_cat(path)` — typed alternative.
- `apex_vfs_grep(pattern, path, flags)` — typed alternative.

Las typed sirven para que el LLM componga llamadas precisas sin parsear bash; `apex_vfs_exec` para sesiones exploratorias.

## 5. Schema nuevo

- `vfs_render_cache(cache_key TEXT PK, rendered TEXT, generated_at TIMESTAMP, source_hash TEXT)`
- `vfs_query_log(id, ts, command, project_slug, hits, latency_ms)` — telemetría para detectar paths calientes (futuro: caching agresivo).

## 6. Tests previstos (~30)

- Path resolver y RBAC (whitelist `vfs_allowed_roots`).
- ls/cat/grep/find sobre mounts reales (fixtures con árbol temporal).
- Renderizado SQL → markdown idempotente.
- grep -r con FTS5 pre-filter (verificar que no se escapa de la whitelist).
- EROFS enforcement (writes fallan con código correcto).
- Cache invalidation (cuando el doctor o un sprint nuevo escribe en `context.db`, el cache se invalida selectivamente).

## 7. Riesgos

- **R1**: rutas virtualizadas pueden quedar stale. **Mitigación**: invalidar cache en cada `apex_doctor_run` y tras cualquier `apex_add_*`.
- **R2**: `grep -r /projects/` sobre 11 proyectos en frío puede ser lento (>2s). **Mitigación**: pre-filtro FTS5 obligatorio antes del scan in-memory; si pattern no es traducible, devolver advertencia + ejecutar igual.
- **R3**: `apex_vfs_exec` con flags raros puede ser un agujero de inyección. **Mitigación**: parser de comandos explícito (no `subprocess`), whitelist de comandos, sin pipes complejos en v1 (sí `|grep`/`|head`/`|wc -l` aceptados como sufijos).

## 8. Lo que S17 NO hace

- Mount real FUSE en el SO (overkill para el caso de uso).
- Escritura desde el VFS (read-only intencional).
- Búsqueda semántica (eso es S18 con embeddings de Granite).
- Watch incremental (cache invalida en eventos APEX, no en `inotify`).

---

# Sprint 18 — Granite Curator opcional (opt-in vía env)

## 1. Goal

Reemplazar las heurísticas ciegas de mantenimiento de contexto (token_filter, handoff plantillero, archive por chars) con un curador local especializado **cuando esté disponible**, manteniendo el comportamiento actual como fallback estricto cuando no lo está. Default: **OFF**. Activación: `export APEX_CURATOR_MODEL=granite4:tiny`.

## 2. Activación y kill switch

```bash
# Curador OFF (default actual): heurísticas tal cual.
unset APEX_CURATOR_MODEL

# Curador ON con Granite 4.1 tiny en Ollama local:
export APEX_CURATOR_MODEL=granite4:tiny

# Curador ON con cualquier modelo Ollama-compatible:
export APEX_CURATOR_MODEL=qwen2.5:7b      # o lo que sea
export APEX_CURATOR_OLLAMA_HOST=http://localhost:11434  # default
export APEX_CURATOR_TIMEOUT_S=3            # fallback a heurística si excede
```

**Cambio en caliente**: la env se lee en cada llamada al curador, no al arrancar el server MCP. Apagar/encender entre prompts vale sin restart.

## 3. Puntos de intercepción

| Hoy (heurística) | Con curador (Granite) | Fallback si timeout/error |
| --- | --- | --- |
| `lib/token_filter.summarize_for_context` corta por chars/líneas | Resumen semántico del tool output | Heurística actual |
| `lib/handoff.serialize_handoff` plantilla fija | Resumen narrativo de la sesión + decisiones clave + verdicts pendientes | Plantilla fija |
| `context-watch.py` umbral fijo | Decisión adaptativa: "¿qué bloque archivar primero?" | Umbral fijo |
| `apex_search` BM25 + keyword | Re-rank de top-20 → top-5 con embeddings Granite | Solo BM25 |

**El curador no decide acciones del agente**, solo *destila*. Si el curador alucina o se equivoca, lo peor que pasa es un resumen pobre; el original sigue archivado en `tool_output_archive`.

## 4. Implementación

- `lib/curator.py` (~280L):
  - `CuratorBackend` interfaz con `summarize(text, max_tokens)`, `embed(text)`, `rerank(query, docs)`.
  - `OllamaCurator` implementación contra Ollama HTTP API.
  - `NoCurator` no-op que devuelve heurística existente.
  - `get_curator()` factory: lee env, devuelve `OllamaCurator` o `NoCurator`. Cachea por env value (no por proceso) para soportar cambio en caliente.
  - Timeout estricto via `httpx` (default 3s). Cualquier excepción → fallback silencioso a heurística.

- **Modificaciones quirúrgicas a módulos existentes**: cada uno añade una llamada `get_curator().summarize(...)` con fallback al código actual. Sin reemplazar nada.

## 5. Schema nuevo

- `curator_calls(id, ts, kind, model, latency_ms, fallback_used BOOL, input_tokens, output_tokens)` — telemetría. Permite medir "¿el curador está aportando?" tras N días de uso.

## 6. Tools MCP nuevas (2)

- `apex_curator_status()` — devuelve `{enabled, model, ollama_host, last_24h: {calls, avg_latency, fallback_rate}}`.
- `apex_curator_test(text, kind)` — prueba determinista que verifica conectividad y devuelve un summarize de ejemplo. Para troubleshooting.

## 7. Tests previstos (~25)

- Mock de Ollama (httpx.MockTransport).
- Fallback automático en timeout, en error 500, en respuesta malformada.
- Opt-in/opt-out por env (incluyendo cambio en caliente entre llamadas).
- Integración con `serialize_handoff`: con curator activo escribe resumen narrativo, sin él plantilla fija.
- Garantía dura: con `APEX_CURATOR_MODEL` unset, **toda la suite sigue corriendo en cualquier Python sin Ollama**. Test gate explícito.

## 8. Riesgos

- **R1**: el curador se vuelve dependencia de facto y dejamos de probar el camino heurístico. **Mitigación**: matriz CI mínima con `unset APEX_CURATOR_MODEL` que ejecuta toda la suite. Sin Ollama disponible en CI.
- **R2**: latencia 3s × N llamadas degrada UX. **Mitigación**: el curador solo se llama en eventos lentos por naturaleza (handoff, archive, search top-K). No en hot path de cada tool call.
- **R3**: Granite 4.1 hereda artefactos de su training. **Mitigación**: ningún output del curador es ground truth — siempre se preserva el original. Detectable en logs.
- **R4**: RAM Slimbook con Granite tiny + servicios actuales. **Mitigación**: granite4:tiny ronda 3-4GB; documentar como requisito mínimo. Si el usuario quiere usar tinyllama u otro modelo más pequeño, el código no asume tamaño.

## 9. Lo que S18 NO hace

- Reemplazar Claude/Opus en ninguna decisión (el curador *destila*, no *decide*).
- Embeddings sobre toda la wiki (eso requiere indexador batch — S19+).
- Reemplazar el Advisor (S15). El Advisor revisa al Executor; el Curador procesa contexto crudo. Roles distintos.
- Forzar Ollama. Cualquier endpoint compatible OpenAI/Ollama API funciona.

---

## Tradeoffs entre los dos sprints

| Item | S17 (VFS) | S18 (Curator) |
| --- | --- | --- |
| Esfuerzo estimado | 2-3 días | 2-3 días |
| Coste marginal runtime | 0 (solo I/O sobre lo que ya hay) | RAM ~3-4GB si activo, 0 si no |
| Reversible | Sí (tools nuevas, nada se rompe al ignorar) | Sí (default OFF) |
| Dependencia nueva | Ninguna | Ollama (opcional) + modelo descargado |
| Beneficio principal | Cross-project navegación sin tax de contexto | Handoffs/archives que conservan significado |

## Orden recomendado

S17 antes que S18 porque S18 puede cura mejor con un VFS que ya estructura el conocimiento cross-project (el curador ve "esto vino de `/projects/tfg-tutor/decisions/`" y mantiene esa traza en el resumen).

---

## Cómo arrancar la sesión nueva tras este handoff

```bash
# Sesión nueva, primer prompt:
apex_resume_session(session_id="868a7915-4dc")
Read .apex/sprints/sprint-15-advisor-blueprint.md       # S15.B en marcha
Read .apex/sprints/sprint-17-vfs-and-sprint-18-curator-blueprint.md   # este archivo
```

El plan a corto plazo sigue siendo cerrar S15.B antes de tocar S17/S18. Estos blueprints son referencia futura, no orden de ejecución inmediata.
