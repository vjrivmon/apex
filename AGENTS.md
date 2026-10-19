# AGENTS.md — APEX

> Fuente única del estado del proyecto. Fusiona lo que antes vivía repartido
> entre este fichero y `BLUEPRINT.md`, que se contradecían entre sí.
>
> **Cómo está organizado:** los HECHOS (tests, tools, tablas, qué sprint tiene
> código escrito) van en el bloque generado `APEX:STATE`, que produce
> `scripts/refresh_state.py` contando el repo. No se editan a mano. Todo lo
> demás es NARRATIVA — decisiones y su porqué — y esa sí se escribe a mano
> porque no caduca.

## Qué es APEX

Sistema de skills + MCP server para Codex que guía el ciclo completo de
desarrollo de software. Usa una BD SQLite contextual por proyecto
(`.apex/context.db`) + un segundo cerebro (ingest/lint/synthesis) + un
dashboard cross-project (`apex-hub`) para que Codex nunca pierda el hilo.

**Arquitectura: puro CLI + MCP + skills.** El frontend/backend web legacy vive
en la rama `archive/legacy-web` y NO se carga en el flujo actual. El único
frontend es `apex-hub` (repo aparte en `~/RoadToDevOps/apex-hub/`).

---

<!-- APEX:STATE:BEGIN -->

## Estado verificado

> Generado por `scripts/refresh_state.py` contando el repo.
> NO editar a mano: se sobreescribe. La narrativa va fuera de este
> bloque. Las filas de hooks globales y de la BD viva dependen de la
> máquina: se reportan, pero `--check` no las cuenta como deriva. La
> sección de contexto es volátil y tampoco fuerza reescritura.

| Métrica | Valor |
|---|---|
| Tests (funciones de test) | 1131 |
| Tests (suite ejecutada) | 1361 pasando, 5 omitidos (snapshot 2026-10-19, 1131 funciones de test) |
| Tools MCP | 64 |
| Skills (`skills/`) | 25 |
| Hooks en disco | 13 |
| Hooks registrados en el proyecto | 8 |
| Hooks registrados globalmente (`~/.claude/settings.json`) | 5 |
| Tablas en el schema (`lib/context_db.py`) | 28 |
| Tablas en la BD viva (`.apex/context.db`) | 35 |

### Artefactos por sprint

Señal mecánica: si el fichero existe, el trabajo se escribió. No dice
si el sprint está *cerrado* — eso es juicio y vive en la narrativa.

| Sprint | Artefactos | Detalle |
|---|---|---|
| S12 roles | presente | lib/roles.py |
| S13 doctor | presente | lib/apex_doctor.py, lib/wrapup_phrases.py |
| S14 skills Pocock | presente | skills/tdd/SKILL.md, skills/diagnose/SKILL.md |
| S15 advisor + traces | presente | lib/advisor.py, lib/reasoning_traces.py |
| S16 advisor feedback | presente | lib/advisor_outcomes.py, lib/advisor_health.py |
| S17 VirtualFS | presente | lib/vfs.py, lib/vfs_grep.py |
| S18 Granite curator | presente | lib/curator.py |
| S19 Advent integration | ausente | ningún artefacto |
| Biblioteca de libros | presente | lib/book_chunker.py, lib/book_corpus.py |

### Contexto del repo (volátil)

Rama `main` · HEAD `f5aad41 docs(agentes): la narrativa recoge lo cerrado en la segunda tanda` · refrescado el 2026-10-19.

<!-- APEX:STATE:END -->

---

## Cómo ejecutar

```bash
# Tests
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -v

# Regenerar el bloque de estado de CLAUDE.md y AGENTS.md
.venv/bin/python scripts/refresh_state.py

# Refrescar el recuento de suite (instantánea con fecha; tarda ~20 s)
.venv/bin/python scripts/refresh_state.py --run-tests

# Comprobar si está desfasado sin escribir (útil en hooks/CI)
.venv/bin/python scripts/refresh_state.py --check
```

`backend/` sigue en el árbol por inercia histórica desde el Sprint 7, declarado
legacy y sin usar. `frontend/` ya no existe: se borró y las instrucciones que lo
mencionaban estaban obsoletas.

---

## Estado por área

### Núcleo (verificado y en uso)

- **Context DB v2** (`lib/context_db.py`) con hybrid retrieval **léxico**
  (70% FTS5/BM25 + 30% keyword LIKE). Ojo: "hybrid" ahí NO significa
  semántico — ambas piernas operan sobre caracteres. El retrieval denso vive
  aparte, en la biblioteca de libros.
- **Wiki scaffold + segundo cerebro** (`lib/wiki_scaffold.py`): `wiki/` estilo
  Karpathy, `.apex/brand/`, `.apex/raw/`, `.apex/releases/`.
- **Ingest pipeline** (`lib/ingest.py`), **self-heal** (`lib/lint.py`),
  **synthesis** con `dream_deep` density-triggered (`lib/synthesis.py`).
- **Scaffold DevOps** (`lib/scaffold_devops.py` + `templates/`).
- **Security gate** (`lib/security_gate.py`): AgentArmor L1-L8, la fase 10.5
  bloquea la 11.
- **Grader** (`lib/grader.py`) + **/goal loop** (`lib/goal_loop.py`).
- **Context hygiene**: `lib/handoff.py`, `lib/token_filter.py`.
- **Roles** (`lib/roles.py`): 5 subagents nativos, mapeados a fases.
- **Apex-doctor** (`lib/apex_doctor.py`): 6 analizadores (A1-A6), trigger
  semántico por frases de cierre.
- **Advisor** (`lib/advisor.py` + `advisor_outcomes/health/tuning`): capa
  preventiva con feedback loop implícito vía facets.
- **Memoria global** (`lib/global_memory.py`): `~/.apex/context.db` es memoria
  append-only de errores GRAVES cross-project. NUNCA es el contexto de un
  proyecto — `_get_db()` lanza si el cwd no tiene `.apex/` propio.

### Vault de Obsidian (2026-09-23)

- `apex-hub/backend/vault_export.py` escribe, tras cada escaneo, una carpeta
  por proyecto en `ApexVault/projects/<id>/` con el mismo contenido que la
  ficha del hub (`<id>.md`, `decisiones`, `errores`, `componentes`,
  `sesiones`). Lee `hub.db`: cada `context.db` se lee una sola vez.
- El MCP añade eventos a `projects/<id>/log.md`. El id es el del hub
  (`vault_project_id`: carpeta en minúsculas, espacios a guiones), no la meta
  `nombre`, que es libre y sin ella todo caía en `unknown-log.md`.
- `notas.md` es del usuario y nadie la toca. Lo personal no-APEX vive en otro
  vault, `~/Documentos/Visi-Personal`.
- El dispatcher rechaza argumentos con sintaxis de otra llamada a tool
  filtrada (`<parameter name=`, `</invoke>` al inicio de línea): había 51
  registros así en 9 proyectos (reparados, copias `.bak-2026-09-23-leaks`).

### Biblioteca de libros (2026-07-21)

Retrieval **denso** sobre los libros técnicos que lee Vicente. Es la primera
pieza de APEX que busca por significado y no por caracteres.

- `lib/book_chunker.py` — trocea `.md` respetando el árbol de headings. Sabe
  que un `#` dentro de un fence es un comentario de Python, no una sección
  (el corpus real tiene 5 de esos), y no separa una fila de tabla de su
  cabecera. **No funde fragmentos de headings distintos**: la citabilidad
  manda sobre el tamaño.
- `lib/book_corpus.py` — `~/.apex/library.db`, un índice con columna de libro
  (no un índice por libro: permite preguntar cruzando títulos). Reindexado
  incremental por `content_sha`, borrado de capítulos desaparecidos, y
  `sync_book()` que se llama antes de cada búsqueda para que sea imposible
  buscar contra un índice viejo.
- `lib/embeddings.py` — cliente ÚNICO de embeddings de APEX (nomic-embed-text
  vía Ollama, 768d). Batch real: una petición por lote, no una por texto.
- Tools: `apex_book_search`, `apex_book_index`, `apex_book_list`. Funcionan
  **sin proyecto APEX** (retorno temprano antes del gate `_get_db()`).

**Dato de diseño medido**: nomic-embed-text es mayoritariamente inglés. Las
preguntas en español contra el corpus inglés aciertan 2/6; traducidas, 6/6.
Por eso la `description` de la tool instruye a enviar la query en inglés. El
usuario pregunta en español; la traducción ocurre por dentro.

**Umbral 0.66**, calibrado sobre el corpus real: preguntas cubiertas por el
libro puntúan 0.69-0.82, preguntas ajenas 0.45-0.58. Por debajo del umbral la
tool no devuelve una lista vacía muda — devuelve el estado "no cubierto" con
la instrucción explícita de decirlo en vez de rellenar con los pesos del
modelo.

### Deuda conocida

Ver `.apex/sprints/DEUDA-2026-07-21.md` para el detalle con evidencia.

- **Errores cross-project: resuelto en el ranking, no en el corpus.**
  `hub.db.errors.recurrence_count` es la recurrencia **local** (sube sólo si el
  mismo error se repite en la misma `context.db`) y el escáner del hub la
  copia tal cual: las 367 filas valían 1, así que el `ORDER BY
  recurrence_count DESC` de `session-start.py` era degenerado y el `LIMIT 5`
  devolvía siempre los mismos errores. Ahora `lib/cross_project_errors.py`
  calcula al leer la recurrencia que el hook anunciaba —**proyectos
  distintos** con la misma firma— y ordena por esa, luego severidad y
  recencia. Queda pendiente la parte de la dirección acordada que no se
  hizo: llevar los errores a un corpus vectorizado consultado bajo demanda,
  como la biblioteca.
- **`code-before-phase5-gate.py` no existe como código.** Sólo quedan dos
  `.pyc` huérfanos (`.claude/hooks/__pycache__/` y `.codex/hooks/__pycache__/`).
  Nunca se fusionó: vivió sólo en `origin/fix/cross-project-tone-2026-07-06`.
  El write-gate de APEX sobre APEX no existe; el que sí existe es
  `phase-gate.py`, que bloquea `apex_set_phase` con exit 2.
- S16.8 (`skills/advisor-feedback/`) diferido por decisión de 2026-05-08.
- **Rama `origin/fix/cross-project-tone-2026-07-06`**: su commit `bce5bf6`
  se ha ido portando por partes (retrieval OR, regla #18, higiene del FTS,
  frontmatter de las skills, postura compartida). Queda sin portar, y es
  trabajo de decisión más que de código: la reescritura del router
  `commands/apex.md`, las skills `effective-agent-skills` y
  `brain-to-docs` (contenido externo de github.com/davidondrej/skills) y el
  `code-before-phase5-gate.py` con sus tests. Decidir fichero a fichero.
- Las capas L1-L6 del gate AgentArmor siguen en `status: partial`. Los
  motivos exactos de cada una están en `.apex/security/L*.md` (sección
  "Cómo desbloquear"), no aquí: esa lista caduca. L7 y L8 están `passed`.

### Cerrado en la auditoría del 2026-10-19

Estos estaban en la lista de deuda y ya no:

- **VFS implementado pero inalcanzable** → cerrado. `lib/vfs_sql_render.py`
  con los renderizadores SQL→markdown, CRUD de `vfs_render_cache` y
  `vfs_query_log`, y las 4 tools `apex_vfs_*` registradas. Se despachan con
  `db=None` (como las de biblioteca) porque el VFS es cross-project: debe
  funcionar sin que el cwd sea un proyecto APEX.
- **`lib/prototype.py:183` — los guards de transición se ignoran** → cerrado.
  Un guard es el *nombre* de una condición (`has_required_fields`), como
  dice la skill; ahora se valida que lo sea, el TUI genera un método
  `guard_<nombre>` por guard y `_fire` lo evalúa: si devuelve False, la
  transición no ocurre y el TUI dice qué guard la bloqueó.
- **El bucle del Advisor era inerte** → cerrado. 7.269 reviews existían
  todos en `pending` con `advice_count=0` porque `update_review_status()` y
  `register_review_outcome()` no tenían ni un call site. Ahora hay cierre
  idempotente, poda de reviews caducados, circuit breaker funcionando y
  `advisor_health()` con datos de verdad.
- **El gate 10.5 no bloqueaba nada** → cerrado. `apex_security_gate` ahora
  persiste un veredicto para la fase 10.5 y entrar en la fase 11 exige que
  ni la fase 10 ni el gate 10.5 bloqueen. La fase 10 además exige gitleaks
  configurado.
- **`refresh_state.py --check` nunca convergía** → cerrado. Comparaba el
  recuento real de tests contra el valor congelado en el fichero, así que
  daba "desfasado" el 100% de las veces. Ahora compara métrica a métrica y
  el contexto volátil (rama, HEAD) no fuerza reescritura.
- **`lib/db_compact.py` huérfano y con dos columnas equivocadas** → cerrado.
  Pedía `advisor_reviews.reviewed_at` y `tool_output_archive.archived_at`,
  que no existen: el DELETE fallaba y el error quedaba escondido. Ahora hay
  `apex_db_compact` en el MCP.
- **13 copias de `find_project_root()`** → cerrado. `lib/project_root.py` es
  la implementación única y el home nunca se resuelve como proyecto.
- **La memoria global contenía estado de otros proyectos** → cerrado. El
  estado residual se exportó a `~/.apex/legacy-project-state-2026-10-19.db`
  y a `~/.apex/rescate-estado-legacy-2026-10-19.json`; la memoria global ya
  sólo contiene `grave_errors`.
- **El retrieval cross-project devolvía 0 hits en consultas naturales**
  → cerrado. FTS5 hace AND implícito (`MATCH "a b c"` exige las tres
  palabras en la MISMA fila) y la consulta cruda se pasaba tal cual. Medido
  contra el `hub.db` real: "memoria global errores graves" daba 0 hits con
  AND y 365 con OR. Ahora `lib/fts_query.py` tokeniza, quita stopwords y
  une con OR; `rank` (BM25) sigue ordenando por relevancia.
- **La regla absoluta #18 era una recomendación sin maquinaria** → cerrado.
  Decía "cross-project retrieval obligatorio" pero nada impedía cerrar la
  fase 3 sin haber consultado el hub. Ahora `lib/cross_project_flag.py`
  registra la consulta por fase y el grader bloquea las fases de decisión
  (0, 2, 3, 5) si no se consultó. Si el hub no está disponible, el check no
  aplica: no se puede exigir lo que no se puede hacer.
- **El índice FTS5 no reflejaba el estado real de los datos** → cerrado. Una
  decisión invalidada seguía apareciendo en la búsqueda, y reindexar
  duplicaba la fila. Ahora `_index_fts()` es idempotente,
  `invalidate_decision()` saca la fila del índice, y `cleanup_fts()` repara
  las BDs ya contaminadas.
- **16 de 25 skills no tenían frontmatter** → cerrado. Sin `name` +
  `description` una skill no es descubrible por descripción: sólo se activa
  si se nombra a mano.
- **Los hooks de Claude y los de Codex se habían separado** → cerrado. Las
  dos familias son ahora idénticas byte a byte, y las 12 copias de la
  resolución de la raíz del proyecto son una sola implementación
  (`lib/project_root.py`). Seis copias de Codex no cortaban en el home y
  resolvían `~/.apex/context.db` como si fuera el contexto de un proyecto.

---

## Roadmap

El orden estricto S17 → S18 → S19 se decidió el 2026-05-08 en lugar de saltar
a S19 por la urgencia de Gap F (gitleaks). Los tres están ejecutados (2026-10-19).

| Sprint | Foco | Estado | Blueprint |
|---|---|---|---|
| S17 | VirtualFS cross-project | cerrado: 4 tools `apex_vfs_*` registradas | `.apex/sprints/sprint-17-vfs-and-sprint-18-curator-blueprint.md` |
| S18 | Granite Curator opt-in vía `APEX_CURATOR_MODEL` | cerrado: opt-in, fallback estricto a la heurística | (mismo fichero que S17) |
| S19 | Advent Integration | Tier 1 cerrado (gitleaks, CI, slash commands, CLAUDE.md APEX-aware). Tiers 2 y 4 sin empezar | `.apex/sprints/sprint-19-advent-integration-blueprint.md` |

Pendientes sin sprint asignado: embeddings sobre la wiki del proyecto
(la infraestructura ya existe en `lib/embeddings.py`), integración Pencil MCP
en fase 2, y el Tier 2/Tier 4 de S19 (`apex_export_session`, reglas
condicionales por componente, hook de `PreCompact`).
---

## Decisiones acumuladas

Las que siguen vigentes y explican por qué el código es como es.

| Decisión | Razón |
|---|---|
| La biblioteca de libros vive en `~/.apex/library.db`, fichero propio | `context.db` es per-proyecto (se duplicaría en ~10 BDs y `_get_db()` la rechaza fuera de proyecto); `~/.apex/context.db` es memoria append-only de errores graves y la biblioteca es mutable |
| Un solo índice con columna de libro, no uno por libro | Permite preguntar cruzando títulos ("qué dicen mis libros sobre X"); el filtro a uno concreto sigue disponible |
| Tool de biblioteca separada, no dentro de `apex_search` | `apex_search` pasa por `_get_db()`, que lanza sin `.apex/`; el Q&A del usuario ocurre fuera de todo proyecto. Mismo precedente que `apex_search_cross_project` |
| Una sola tool de búsqueda para el usuario y para el Architect | Comparten chunks, vectores y citas; solo difieren en cómo se redacta la respuesta, y eso es prompting, no código |
| Sin grafo de entidades sobre los libros | Verificado: 0 wikilinks en los 7 capítulos. Fabricar el grafo costaría ~250 llamadas LLM e introduciría alucinación justo donde el requisito es trazabilidad |
| Sin numpy/sqlite-vec/faiss | 4.500 fragmentos se recorren en ~155 ms en Python puro. Reconsiderar hacia los 30 libros |
| Sin FTS5 sobre los fragmentos del libro | Medido: el híbrido léxico da 3/6 igual que el denso solo. El léxico no cruza idiomas |
| Reindexado automático al buscar, no watcher de ficheros | Vicente confirmó que los capítulos entran en bloque, nunca a medias. Comparar hashes es local y barato, y hace imposible buscar contra un índice desactualizado |
| Los hechos del AGENTS.md y del CLAUDE.md se generan, no se escriben | Auditoría 2026-07-21: ~42 afirmaciones falsas acumuladas. El 85% era derivable con un comando. Auditoría 2026-10-19: el control de deriva estaba roto (comparaba el recuento real contra el congelado) y AGENTS.md era una copia a mano |
| Fuera las cifras de líneas por módulo | 8 de 15 estaban mal (hasta +116%) y no aportan nada a quien lee |
| 3 enums de rating (`useful`/`not_useful`/`unclear`) | `unclear` no es rating sino ausencia de señal: se excluye del denominador del FP rate |
| Solo enums, nunca texto libre, en los outcomes del advisor | Privacidad: los facets pueden contener briefs o código sensible |
| Cooldown 7 días entre auto-tunings | Anti-oscilación |

---

## Errores conocidos a evitar

1. Construir frontend antes de verificar backend.
2. No investigar fuentes de datos antes de escribir scrapers.
3. Tomar decisiones de diseño sin consultar al usuario.
4. SPEC monolítica sin checkpoints.
5. Hardcoded data en frontend.
6. Sin tildes ni eñes en español.
7. CORS abierto y sin auth al inicio.
8. No generar edge cases antes del código.
9. Asumir siempre "app web con dashboard".
10. No usar awesome-design-md como referencia visual.
11. Ir de prisa en vez de diseñar bien.
12. **Fiarse de un documento de estado sin verificarlo contra el repo.** Este
    fichero llegó a decir 695 tests cuando había 722, y a marcar como
    pendientes sprints cerrados hacía meses. Si un dato importa para una
    decisión, cuéntalo.

---

## Lecciones de proceso

1. **Verificar antes de cerrar.** `pytest -q` antes de declarar verde. Y si
   una pieza tiene comportamiento observable (un retrieval, un parser),
   ejecutarla contra datos reales, no solo correr sus tests: los 16 tests del
   chunker pasaron solo después de que cinco fallos destaparan tres bugs que
   el código "parecía" no tener.
2. **Auditar antes de presentar decisiones.** Distinguir explícitamente entre
   decisiones ya tomadas que se están modificando y las genuinamente abiertas.
3. **No emojis** en código ni documentación. Español con tildes y eñes.
4. **Cuando el grader o los tests fallen, no bypasear**: causa raíz y fix
   limpio.
5. **No inventar un desacuerdo con el usuario.** Si algo parece un riesgo,
   comprobar primero que el usuario lo ha pedido de verdad; citar una
   autoridad para respaldar una suposición no verificada es peor que callarse.
