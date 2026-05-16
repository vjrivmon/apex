# Informe de Análisis y Mejoras del Sistema APEX

> Análisis independiente del estado actual (Sprint 16, 545 tests, 53 MCP tools).
> Fecha: 2026-05-16

---

## 1. Resumen Ejecutivo

APEX es un sistema ambicioso y bien fundamentado para desarrollo guiado por fases
con Claude Code. La arquitectura hexagonal, la separación limpia entre módulos lib/
y la integración MCP están bien ejecutadas. El sistema tiene madurez notable en su
capa de memoria (context.db, reasoning traces, advisor feedback loop) pero presenta
oportunidades significativas en robustez operativa, seguridad productiva, rendimiento
y alineación con las prácticas emergentes de "context engineering" de Karpathy.

---

## 2. Fortalezas Arquitectónicas

### 2.1 Context DB como sistema de memoria
La implementación de `context_db.py` con progressive disclosure (compact/timeline/full),
temporal facts (patrón Graphiti), y hybrid retrieval (BM25 + keyword overlap) es
sólida. Las 17+ tablas cubren decisiones, errores, componentes, traces, advice,
outcomes, y tuning history. El auto-migrador `_ensure_db_schema` es correcto.

### 2.2 Separación de responsabilidades
Cada módulo en lib/ tiene una única responsabilidad: `advisor.py` (pacing/throttle),
`advisor_outcomes.py` (computación), `advisor_health.py` (dashboard),
`advisor_tuning.py` (auto-ajuste). Esta granularidad facilita testing y evolución.

### 2.3 Políticas de bloqueo no relajadas
La regla fundamental del grader ("el bloqueo determinista nunca se relaja por el LLM")
es arquitectónicamente correcta. El merge de verdicts en `merge_verdicts()` respeta
esta invariant con `final_block = determinista.should_block or llm.should_block`.

### 2.4 Throttle y anti-oscilación
El circuit breaker del Advisor (backoff a 16 calls tras 3 empty streaks), el cooldown
de 7 días del auto-tuner, y el mínimo de 20 outcomes por categoría son defensas
adecuadas contra ruido y oscilación.

### 2.5 Progressive disclosure en comandos
El patrón de `commands/apex.md` como router que carga fases bajo demanda
(`commands/phases/NN-*.md`) es óptimo para controlar consumo de tokens en el
contexto de Claude Code.

---

## 3. Debilidades Arquitectónicas

### 3.1 MCP server monolítico (CRÍTICO)
`mcp/apex_server.py` tiene ~3000 líneas con 53 tools registrados en un único
archivo. Cada tool es un handler inline. Esto crea:
- Dificultad para testing aislado de handlers MCP
- Riesgo de conflictos de naming (ya hay duplicación: `apex_security_gate`
  aparece listada dos veces en el CLAUDE.md)
- Carga cognitiva alta al añadir herramientas
- El path de importación se manipula manualmente
  (`sys.path.insert(0, str(_apex_root / "lib"))`)

**Propuesta**: Factorizar handlers en `mcp/handlers/` con un registry decorado.
Ejemplo: `@register_tool("apex_get_context")` en cada módulo handler.

### 3.2 Sync vs Async inconsistente
`context_db.py` define `ApexContextDB` con métodos `async` usando `aiosqlite`, pero
los módulos del Advisor (`advisor.py`, `advisor_outcomes.py`, `advisor_health.py`,
`advisor_tuning.py`) usan `sqlite3` síncrono directamente. Esto crea:
- Dos caminos de acceso a la BD (async vía ApexContextDB, sync vía `_conn()`)
- Imposibilidad de compartir conexiones
- El MCP server tiene que bridgear entre ambos mundos

### 3.3 Hooks proliferando sin métricas
11 hooks registrados en `.claude/hooks/`, cada uno es un script Python independiente
que se lanza como subprocess. No hay métricas de:
- Tiempo de ejecución acumulado por sesión
- Frecuencia real de triggers
- Tasa de fallos silenciosos (muchos hooks tienen `except Exception: return 0`)
- Impacto en latencia del prompt loop

### 3.4 Schema de context.db sin compactación
Con 17+ tablas y tablas de crecimiento continuo (`tool_call_log`, `tool_output_archive`,
`reasoning_traces`, `advisor_reviews/advice`, `advice_outcomes`), no hay mecanismo
de:
- Compactación o archivado de datos antiguos
- Limpieza de `tool_call_log` que crece indefinidamente
- VACUUM periódico
- Rotación de `tool_output_archive`

### 3.5 Dependencia de paths hardcodeados
`_HUB_DIR = Path.home() / "RoadToDevOps" / "apex-hub"`, `_OBSIDIAN_VAULT =
Path.home() / "Documents" / "ApexVault"`. Estos paths asumen una estructura de
directorio específica del usuario. Si el sistema se distribuyeron fallan.

---

## 4. Análisis de "Context Engineering" (Karpathy)

Karpathy articula principios clave para sistemas agentic: optimizar el contexto
que llega al LLM, minimizar ruido, y construir loops de feedback cerrados.
APEX se alinea parcialmente pero tiene gaps importantes:

### 4.1 Falta compresión inteligente de contexto
El sistema usa chars/4 como heurística de tokens (`_truncate_to_tokens`). El bundle
del advisor (2500 tokens) se trunca con una estrategia head+tail. Falta:
- **Compresión semántica**: resumir secciones de contexto por relevancia a la fase
  actual, no solo por longitud
- **Deduplicación cross-sesión**: decisiones que se reafirman en múltiples sesiones
  podrían compactarse
- **Señal vs ruido**: el bundle incluye `recent_tool_calls` (últimas 20) que aportan
  poco señal para el advisor; las trazas son más informativas

### 4.2 Falta retrieval contextual por fase
El advisor recibe el mismo tipo de bundle independientemente de la fase. Un bundle
para fase 0 (socrático) debería priorizar preguntas abiertas y contexto de mercado;
uno para fase 9 (testing) debería priorizar cobertura y patrones de tests. La
fase actual se incluye pero no se usa para ponderar el contenido.

### 4.3 Falta evaluación de calidad del contexto
No hay métricas de si el contexto inyectado es útil. Los hooks inyectan contexto
(sinAdvisor, session-start, advice-injector) pero no hay señal de feedback de si
ese contexto mejoró o empeoró la calidad de la respuesta del agente.

### 4.4 Missing: structured output de LLM para feedback loop
El grader parsea JSON del LLM con `parse_llm_verdict()` (tolerante pero frágil).
No hay validación de schema contra un JSON Schema, lo que puede causar decisiones
basadas en datos parcialmente parseados. La heurística `text[start:end+1]` es
vulnerable a JSON malformado con llaves en strings.

---

## 5. Propuestas de Mejora (Priorizadas por Impacto)

### P0 — Impacto inmediato en estabilidad y productividad

#### 5.1 Compactación y limpieza de context.db
- Implementar `apex_db_compact()` que ejecute VACUUM + limpieza de tablas de logs
  con datos >30 días (`tool_call_log`, `tool_output_archive`, `reasoning_traces`)
- Añadir como tool MCP y ejecutar automáticamente al final de sesión (hook)
- **Riesgo actual**: en 50 sesiones (~5 semanas), `tool_call_log` tendrá ~1000+
  filas y las queries con ORDER BY id DESC LIMIT 20 se ralentizarán

#### 5.2 Unificar acceso a SQLite
Migrar los módulos Advisor (`advisor.py`, `advisor_outcomes.py`, `advisor_health.py`,
`advisor_tuning.py`) de `sqlite3.connect()` síncrono a usar `ApexContextDB` o
al menos una función `_get_db()` compartida que gestione WAL mode, busy_timeout,
y cierre correcto. Actualmente hay 6+ puntos de apertura de conexión independientes.

#### 5.3 Métricas de hooks
Añadir logging estructurado a cada hook:
```python
# En cada hook, al inicio:
import time
_start = time.monotonic()
# Al final:
elapsed_ms = (time.monotonic() - _start) * 1000
# Escribir a .apex/hook_metrics.jsonl
```
Esto permite detectar hooks lentos (el doctor hook tiene timeout 8s pero la mayoría
no tiene timeout).

### P1 — Impacto en la experiencia del desarrollador

#### 5.4 Factorizar MCP server en handlers
Crear `mcp/handlers/` con un módulo por dominio:
```
mcp/handlers/
├── context.py      # get_context, set_phase, search
├── decisions.py    # add_decision, invalidate_decision
├── components.py   # add_component, update_component
├── advisor.py      # advisor_review, record_advice, etc.
├── grader.py       # grader_evaluate
├── roles.py        # install_roles, recommend_role, invoke_role
├── doctor.py       # doctor_run
├── forge.py        # skill_forge_scan/approve/reject
└── ...
```
Registry con decorador `@register_tool` que el server itera al `list_tools`.

#### 5.5 Advisor con contexto fase-aware
En `build_bundle()`, usar `phase` para filtrar y ponderar:
- **Fases 0-1**: priorizar cross-project errors y decisiones de mercado
- **Fases 2-3**: priorizar decisions de diseño y reasoning traces
- **Fases 4-5**: priorizar edge cases y componentes
- **Fases 6-8**: priorizar errores recurrentes y tool_call patterns
- **Fases 9-10**: priorizar grader verdicts y security findings
- **Fases 11-14**: priorizar doctor proposals y stale handoffs

#### 5.6 JSON Schema para verdicts del grader
Definir un JSON Schema y validar con `jsonschema.validate()` antes de parsear.
Evitar que un LLM que responda con un JSON parcial cause un verdict incorrecto.

### P2 — Impacto en seguridad productiva

#### 5.7 Rate limiting para hooks
Los hooks de UserPromptSubmit se ejecutan en cada prompt del usuario. Si el usuario
escribe rápido, los hooks de `advisor-outcome-watch` (que corre `compute_outcomes`
con filesystem scan) y `advice-injector` (que lee la BD) se ejecutan en cada
prompt. Implementar un debounce de 2-3 segundos entre ejecuciones del mismo hook.

#### 5.8 Sanitización de inputs en MCP tools
Los tools MCP reciben parámetros del LLM que podrían contener payloads maliciosos.
Verificar que:
- `description` de `apex_add_decision` no contenga SQL (las queries usan
  parámetros pero los strings se muestran en contextos futuros)
- `reason` en `apex_dismiss_advice` no contenga inyección de contexto
  (el string se inyecta al agente vía `additionalContext`)
- `session_id` en las tools tenga formato esperado (no paths arbitrarios)

#### 5.9 Auditoría de paths en hooks
Los hooks navegan hacia arriba desde CWD hasta encontrar `.apex/`. Un atacante que
ejecute Claude Code en un directorio crafted podría hacer que el hook lea/escriba
una `context.db` controlada por el atacante. Añadir validación de que `.apex/` está
en un path dentro del proyecto esperado, o al menos que `context.db` no es un
symlink.

### P3 — Impacto en escalabilidad del framework

#### 5.10 Reducir la superficie de tools (53 -> ~35 efectivas)
Análisis de redundancias y oportunidades de consolidación:

**Tools candidatas a consolidación:**
| Tools actuales | Propuesta |
|---|---|
| `apex_add_decision` + `apex_invalidate_decision` + `apex_add_component` + `apex_update_component` + `apex_add_error` + `apex_add_next_step` + `apex_complete_step` | Consolidar en `apex_record(type, ...)` con discriminated union. Reducir de 7 a 2 tools: `apex_record` y `apex_query` |
| `apex_advisor_review` + `apex_record_advice` + `apex_dismiss_advice` + `apex_advisor_health` + `apex_advisor_compute_outcomes` + `apex_rate_advice` + `apex_advisor_apply_tuning` | Consolidar en `apex_advisor(action, ...)` con action como parámetro enum |
| `apex_skill_forge_scan` + `apex_skill_forge_approve` + `apex_skill_forge_reject` | Consolidar en `apex_skill_forge(action, slug, ...)` |
| `apex_install_roles` + `apex_recommend_role` + `apex_invoke_role` | Consolidar en `apex_role(action, ...)` |
| `apex_grader_evaluate` + `apex_goal_loop` | Mantener separadas (responsabilidades distintas) |
| `apex_handoff_write` + `apex_resume_session` + `apex_archive_output` + `apex_get_archived` | Consolidar en `apex_session(action, ...)` |

**Tools candidatas a eliminación:**
| Tool | Razón |
|---|---|
| `apex_search_cross_project` (duplicada en tabla apex.md) | Aparece dos veces en la tabla de herramientas del CLAUDE.md |
| `apex_security_gate` (duplicada) | Aparece dos veces en la tabla de herramientas del CLAUDE.md |

**Tools candidatas a adición (missing):**
| Tool | Justificación |
|---|---|
| `apex_db_compact` | Compactación y limpieza (ver P0 5.1) |
| `apex_export_session` | Exportar estado completo de sesión a Markdown (referenciado en S19 pero no implementado) |
| `apex_diff_context` | Mostrar qué cambió entre sesiones (delta de decisiones, errores, componentes) |
| `apex_prompt_template` | Generar prompts pre-fase con contexto relevante (reducir uso de ToolSearch) |
| `apex_benchmark` | Benchmark de latencia/throughput de los propios tools (dogfooding) |

#### 5.11 Eliminar backend/frontend legacy
Según el propio CLAUDE.md, los directorios `backend/` y `frontend/` viven en
`archive/legacy-web` y no se usan. El `.claude/CLAUDE.md` interno aún referencia
FastAPI + ChromaDB + Next.js que confunde a Claude Code cuando arranca. Mover
estos directorios a la rama `archive/legacy-web` y actualizar `.claude/CLAUDE.md`
para que solo refleje la arquitectura actual (MCP + skills + context.db).

---

## 6. Análisis de Gaps en las 14 Fases

### 6.1 Fase 0 (Socratic): sin validación de calidad de inputs
El socratic interview recoge inputs del usuario pero no verifica que cubren un
mínimo de información. Un usuario que responde "sí" a todo produce un plan débil.

**Propuesta**: Validar que la sesión socratica tiene >=N datos de mercado,
>=M usuarios objetivo, >=K competidores mencionados antes de cerrar la fase.

### 6.2 Fase 1 (Solution Type): demasiado temprana
Evaluar el tipo de solución después del socratic es correcto, pero la fase 1
actual (detectar OS) es demasiado ligera. Debería también evaluar:
- Restricciones de infraestructura del usuario
- Presupuesto (API costs vs local-only)
- Requisitos de offline
- Audiencia técnica vs no-técnica

### 6.3 Fase 4 (Edge Cases): sin métricas de completitud
La fase exige "TODOS los posibles, sin limite" pero no hay métricas objetivas
de completitud. El grader no tiene checks deterministas para fase 4.

**Propuesta**: Añadir check `edge_cases_count >= 10` (heurística) y
`edge_cases_have_categorization = True` (categorizados por tipo).

### 6.4 Fase 5 (Scaffold): sin verificación de compilación
La fase dice "verificar que compila" pero el grader no tiene un check
determinista para isso. Un scaffold con errores de importación pasa sin
detección.

**Propuesta**: Ejecutar `python -c "import <package>"` o `ruff check .` como
check determinista en fase >=5.

### 6.5 Fase 8 (Integración): sin health checks del sistema
La fase conecta componentes pero no verifica que cada componente expone health
checks o que la integración puede manejar fallos de componentes individuales.

### 6.6 Fase 13 (Escalado): subutilizada
La fase tiene un único paso de profiling. Debería incluir:
- Benchmark de base de datos (queries lentas)
- Análisis de memoria
- Carga simulada (k6, locust)
- Plan de escalado horizontal vs vertical

### 6.7 Falta una fase de documentación
No hay fase dedicada a documentación del proyecto. La documentación se reparte
entre wiki (sistema interno) y la entrega final. Una fase 13.5 de
"documentación y handoff" entre escalado y mantenimiento sería valiosa,
incluyendo: README actualizado, API docs, CONTRIBUTING, CHANGELOG.

### 6.8 Fase 14 (Mantenimiento): sin automation
La fase describe qué debería hacer pero no automatiza:
- Renovación automática de dependencias (Dependabot, Renovate)
- Cleanup de branches stale
- Auditoría de licencias
- Métricas de salud del proyecto

---

## 7. Mejoras al Sistema Advisor

### 7.1 Bundle con priorización por relevancia
El bundle actual incluye:
- phase (1 row)
- recent_decisions (últimas 3)
- blocking_verdicts (últimas 3)
- recent_traces (últimas 5)
- recent_tool_calls (últimas 20)

**Problema**: 20 tool calls aportan poco señal al advisor. En su lugar:
- Incluir **resumen de patrones** de tool_call_log (ej: "llamó `apex_add_error`
  5 veces en fase 3" es más útil que los 5 calls individuales)
- Incluir **error clusters** (errores con recurrence_count >= 2)
- Incluir **doctor proposals abiertas** (el advisor puede dar seguimiento)

### 7.2 Advisor con memoria cross-sesión
El advisor actual solo ve la sesión actual. Debería tener acceso a:
- Patrones de advisor dismissals en sesiones anteriores (si el usuario
  descarta `forgotten_tool` 3 veces, el advisor debería dejar de emitir ese tipo)
- Historial de fp_rate por kind en las últimas 10 sesiones
- Métricas de effectiveness: ¿cuántas advice cards resultaron en cambios
  medibles?

### 7.3 Auto-tuning con más parámetros
El auto-tuner actual solo muta 4 constantes. Ampliar a:
- `bundle_max_tokens` (si el advisor truncó 3+ veces consecutivas, aumentar)
- `active_advice_window_sec` (si las cards se descartan por "ya no aplica",
  reducir la ventana)
- `empty_streak_threshold` (si el circuit breaker se activa frecuentemente,
  el umbral podría estar demasiado bajo)

### 7.4 Advisor como agente autónomo
El advisor actual es reactivo: espera a que el hook lo invoque. Una extensión
sería que el advisor pueda:
- Monitorear el progreso sin intervención y emitir alertas proactivas
- Comparar la velocidad actual del proyecto con estimaciones anteriores
- Detectar cuando un sprint se está tardando más de lo esperado

---

## 8. Análisis de la Superficie de Tools (53 herramientas)

### 8.1 Distribución por dominio
| Dominio | Tools | % |
|---|---|---|
| Contexto/Estado (get_context, set_phase, search) | 5 | 9% |
| Registro (decisiones, errores, componentes, next_steps) | 7 | 13% |
| Wiki/Synthesis | 3 | 6% |
| Grading/Goal | 2 | 4% |
| Handoff/Session | 4 | 8% |
| Advisor (review, advice, outcomes, health, tuning) | 7 | 13% |
| Security Gate | 1 | 2% |
| DevOps scaffold | 1 | 2% |
| Design/Research | 3 | 6% |
| Reverse engineering | 3 | 6% |
| Portfolio | 2 | 4% |
| Roles | 3 | 6% |
| Skill Forge | 3 | 6% |
| Doctor | 1 | 2% |
| Library Ingest | 1 | 2% |
| Browser trace | 1 | 2% |
| Prototype | 1 | 2% |
| Hub bridge | 1 | 2% |
| **Total** | **53** | |

### 8.2 Tools con uso probable bajo
- `apex_synthesize` (density-triggered, raramente invocado manualmente)
- `apex_search_cross_project` (requiere apex-hub corriendo)
- `apex_portfolio_draft` (solo para publicación a vr-web)
- `apex_design_md_validate` (solo fase 2)
- `apex_browser_trace` (fase 8/9, poco usado en desarrollo temprano)

**Recomendación**: No eliminar, pero documentar claramente qué tools son
"core" (usadas en toda fase) vs "específicas de fase" (usadas solo en 1-2 fases).

### 8.3 Tools missing para el workflow actual
1. **`apex_get_metrics`**: Devolver métricas agregadas del proyecto (total
   decisiones, total errores, fases completadas, tests pasando, etc.)
2. **`apex_compare_sessions`**: Comparar dos sesiones para detectar progreso
3. **`apex_template`**: Aplicar templates predefinidos (no solo DevOps, sino
   también project structure, config files, etc.)
4. **`apex_changelog`**: Generar changelog automáticamente de decisiones y
   cambios de fase

---

## 9. Integración con Hermes Agent

### 9.1 Contexto disponible
Hermes Agent corre en la misma máquina que APEX. Hay varias oportunidades
de integración:

### 9.2 MCP bridge APEX -> Hermes
Hermes puede consumir las tools MCP de APEX como si fueran herramientas
nativas. Configurar en hermes-agent:
```json
{
  "mcpServers": {
    "apex": {
      "command": "python3",
      "args": ["/home/vicente/apex/mcp/apex_server.py"]
    }
  }
}
```
Esto permitiría que Hermes ejecute `apex_get_context`, `apex_search`, y
`apex_grader_evaluate` directamente.

### 9.3 Hermes como advisor backend alternativo
Actualmente el Advisor usa un subagent Opus de Claude Code. Hermes con
grok-4.3 podría servir como advisor alternativo o segundo opinion:
```python
# En vez de invocar Task(subagent_type='apex-advisor'):
# Llamar a Hermes con el bundle del advisor
hermes_prompt = advisor.build_bundle(db_path, session_id)
# Hermes evalúa y devuelve advice cards
```

### 9.4 Hermes para testing de hooks
Los hooks de APEX se ejecutan como subprocessos Python. Hermes podría:
- Ejecutar la suite de tests de APEX (545 tests) automáticamente
- Monitorear el log de hooks para detectar fallos
- Ejecutar `apex_doctor_run` periódicamente vía terminal background

### 9.5 Gestión de contexto compartido
Hermes escribe su propio contexto en `/home/vicente/.hermes/`. APEX escribe
en `.apex/context.db` por proyecto. Podrían compartir un hub de métricas
para correlacionar:
- Fases del proyecto (APEX) con sesiones de desarrollo (Hermes)
- Errores detectados por el grader (APEX) con patches aplicados (Hermes)
- Advisor outcomes (APEX) con calidad de código generada (Hermes)

---

## 10. Mejoras de Seguridad

### 10.1 Más allá de AgentArmor
AgentArmor (8 capas) cubre la auditoría pre-deploy pero no cubre:

#### 10.1.1 Seguridad del propio APEX
- Los hooks Python ejecutan código arbitrario como subprocess. Si un
  atacante modifica un hook (o inyecta uno vía `.claude/settings.json`),
  tiene ejecución de código en cada prompt del usuario.
- **Mitigación**: Checksum de hooks en `session-start.py` con verificación
  contra `.claude/hooks/checksums.sha256`.

#### 10.1.2 Protección de context.db
- `context.db` contiene decisiones, errores, y planes del proyecto. Es
  información sensible.
- **Mitigación**: No verificar en git, añadir a `.gitignore`. Añadir
  verificación de permisos (no world-readable).

#### 10.1.3 Seguridad del Hub bridge
- El hub escucha en `localhost` sin autenticación. Cualquier proceso local
  puede enviar eventos al hub.
- **Mitigación**: Añadir un token simple de autenticación header
  (`X-APEX-Token`) o limitar a UID del usuario.

#### 10.1.4 Validación de output de LLM
- El grader parsea output JSON del LLM. Un output malicioso podría contener
  instrucciones si se muestra al usuario sin sanitización.
- **Mitigación**: Nunca mostrar raw LLM output al usuario; siempre
  renderizado.

### 10.2 Detección de secretos mejorada
`library_ingest.py` ya tiene regex anti-keys para skills importadas. Ampliar
a:
- Verificar que `context.db` no contiene secretos (scan periódico)
- Verificar que hooks no loguean tokens o credenciales
- Verificar que `.apex/handoff/` no contiene datos sensibles en plaintext

### 10.3 Signing de artifacts
Los archivos en `.apex/` no tienen integridad verificada. Un atacante que
modifique `.apex/security/L1-ingestion.md` podría marcar una capa como
`passed` sin evidencia real.
- **Mitigación**: Firma HMAC de archivos de seguridad con key derivada del
  project root.

---

## 11. Mejoras de Performance y UX

### 11.1 Latencia del MCP server
El MCP server carga 17+ módulos Python en cada arranque. El tiempo de
arranque se mide en segundos (imports pesados como `httpx`, `anthropic`,
`yaml`). Optimizaciones:
- **Lazy imports**: Importar módulos solo cuando se invoca la tool correspondiente
- **Pre-compilar regex**: `EMOJI_RE` y otros se compilan al importar; mover
  a constants compartidas
- **Connection pooling**: El server crea una nueva conexión SQLite por tool
  call; pool de 1-2 conexiones reduciría overhead

### 11.2 Progreso visual del workflow
El usuario no tiene una vista clara del progreso general. El `apex_get_context`
devuelve datos pero no un dashboard. Propuesta:
- Un resumen tipo "Barra de progreso: 9/15 fases completadas, fase actual:
  Testing (4/8 sub-pasos)"
- Mostrar en `session-start.py` al inicio de cada sesión
- Integrar con `apex-hub` para vista persistente

### 11.3 Reducir fricciones del flow-guide
- El usuario tiene que recordar ejecutar `ToolSearch("apex")` al inicio
  de cada sesión. El hook `session-start.py` podría auto-cargar las tools
  o al menos inyectar un recordatorio más prominente
- Los 11 hooks se ejecutan en cascada; optimizar el orden para que los
  más rápidos y críticos (phase-gate) vayan primero
- Añadir un "modo rápido" que deshabilite hooks no esenciales
  (advisor-outcome-watch, post-tool-archive) para sesiones exploratorias

### 11.4 Handoff entre sesiones más robusto
El handoff actual escribe un `.md` en `.apex/handoff/`. Problemas:
- No comprime el estado (solo serializa lo que cabe en un prompt)
- No tiene checksum de integridad
- No detecta si el handoff está desactualizado
- No prioriza qué del handoff es más relevante para la sesión siguiente

**Propuesta**: Handoff comprimido con priorización (errores activos >
fase actual > decisiones recientes > componente estado) y checksum SHA256.

### 11.5 Caché de resultados de tools
Varias tools son idempotentes y devuelven lo mismo si el input no cambia:
`apex_get_context(level="compact")`, `apex_advisor_health()`,
`apex_recommend_role(phase=N)`. Un caché con TTL de 30 segundos evitaría
lecturas redundantes a la BD.

---

## 12. Recomendaciones de Proceso

### 12.1 Technical Debt visible
Hay deuda técnica documentada pero no priorizada:
- S16.8 (skill advisor-feedback): ~30 min, 0 tests
- Legacy web en `backend/` y `frontend/`: confunde a `.claude/CLAUDE.md`
- Backend/CLAUDE.md interno aún referencia FastAPI + ChromaDB (obsoleto)
- Tabla `tool_call_log` sin compactación

**Propuesta**: Añadir un script `apex_debt.py` que escanee el repo y
devuelva deuda técnica priorizada (inspirado en `apex_doctor` pero para
el propio repo de APEX).

### 12.2 Testing de integração MCP
Los 545 tests son unitarios. Falta testing de integración que ejecute
tools MCP reales contra una `context.db` temporal:
```python
async def test_mcp_apex_get_context():
    db = ApexContextDB(":memory:")
    await db.initialize()
    # Simular llamada MCP
    result = await handle_tool("apex_get_context", {"level": "compact"})
    assert "phase" in result
```

### 12.3 Documentación de tools para usuarios finales
Las tools MCP están documentadas en `apex.md` con una tabla plana. Falta:
- Ejemplos de uso concreto para cada tool
- Errores comunes y cómo resolverlos
- Guía de "qué tool usar cuando" según la fase
- Comparación con la alternativa manual (hacerlo sin tools)

---

## 13. Roadmap Sugerido (Post-S16)

| Sprint | Foco | Prioridad | Esfuerzo estimado |
|---|---|---|---|
| S17 | Compactación DB + métricas hooks + limpieza legacy | P0 | 2-3 días |
| S18 | Factorizar MCP server en handlers + caché | P1 | 3-4 días |
| S19 | Advisor fase-aware + bundle mejorado | P1 | 2-3 días |
| S20 | Seguridad: checksum hooks + signing artifacts | P2 | 1-2 días |
| S21 | Testing integración MCP + JSON schema grader | P1 | 2-3 días |
| S22 | Hermes Agent integration (MCP bridge) | P2 | 1-2 días |
| S23 | UX: progreso visual + handoff mejorado | P2 | 2-3 días |

---

## 14. Conclusión

APEX es un sistema notablemente completo para ser un proyecto personal. La
arquitectura es sólida, la cobertura de tests es alta (545), y la iteración
sprint a sprint es disciplinada. Las principales oportunidades están en:

1. **Operabilidad**: compactación de BD, métricas de hooks, eliminación de
   deuda técnica legacy
2. **Robustez**: factorizar el MCP server, unificar acceso a SQLite, validar
   outputs del LLM
3. **Inteligencia contextual**: advisor fase-aware, compresión semántica,
   feedback loop cerrado
4. **Seguridad productiva**: checksum de hooks, protección de artifacts,
   sanitización de inyección de contexto

El sistema está en una posición buena para pasar de "funcional" a
"robusto y mantenible". Los próximos 3-4 sprints de hardening tendrán
mayor impacto que features nuevas.
