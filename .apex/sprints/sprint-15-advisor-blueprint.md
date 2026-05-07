# Sprint 15 — The Advisor Strategy + reasoning_traces + /prototype

> Blueprint completo. Auto-contenido. Diseñado para leer al inicio de una sesión limpia tras `apex_resume_session(session_id="b79459e8-d02")`. Última actualización: 2026-05-07. Sesión origen: `b79459e8-d02`.

---

## 0. Contexto previo (para que la nueva sesión no pierda nada)

### 0.1 Origen de la idea

Vicente trajo tres referencias en la sesión origen que confluyen en este sprint:

1. **Corpus Hermes 3 / MIMO V2.5 (OusiaResearch)** — 14,726 trazas de razonamiento agentivo publicadas en HuggingFace bajo CC BY-NC 4.0 (`OusiaResearch/mimo-v25-agentic-reasoning-traces`). Dos partes: 9,287 trazas generales + 5,439 especializadas en 15 categorías diagnósticas (epistemic self-awareness, adversarial robustness, cascading failure recovery, multi-turn negotiation, consequential engineering, moral hazard recognition, socratic self-correction, embodied somatic intelligence, narrative causality, multi-agent coordination, sysadmin blast radius, data science accountability, frontend UX consequence, devops cost awareness, long-horizon consequences). El insight: medir *cómo* razona un agente, no solo *si* completó la tarea.

2. **The Advisor Strategy (imagen Anthropic)** — patrón Executor/Advisor/Shared context. Executor (Sonnet) corre cada turno; Advisor (Opus) on-demand revisa el shared context y manda advice via tool call al Executor. Vicente reconoce este patrón como exactamente lo que falta en APEX hoy.

3. **Ruflo + flujo Matt Pocock** — Vicente NO quiere copiar la arquitectura Ruflo (5,706 entries inyectadas/mensaje, hive-mind single-process, agent_spawn que no spawnea, ~45 tools stubbed según ADR-095). Quiere copiar el **flujo de skills**: `grill-with-docs → handoff → prototype → handoff → to-prd → to-issues → sandcastle → improve-architecture`. Pocock añade que un **TUI ejecutable de business logic** da feedback más rico que una spec en prosa.

### 0.2 Diagnóstico del dolor real

Las palabras de Vicente: *"el máximo error ahora mismo de /apex es que a pesar de crear herramientas pertinentes, se le olvida al propio Claude Code de hacerle caso, lo que supone el estar recordándoselo y es cuando me canso"*.

Caso concreto que lo demuestra: en la sesión `d8a7c98a-0d7a-4207-af67-60a648a2753b` Vicente configuró el hook `context-watch.py` para avisar al 40% del context limit. Ese hook **se activa en /apex** (lo vimos disparándose 3 veces en la sesión origen al 45%, 65.9%, 74.5%), pero Vicente reporta que en otros proyectos no lo detecta funcionando. Hipótesis a verificar al inicio de la nueva sesión: el hook está registrado en `~/.claude/settings.json` o solo en `apex/.claude/settings.json`. Si está solo en project-level, ese es el bug.

El sprint aborda dos capas del olvido:
- **Capa preventiva**: el Advisor lee el shared context cada N turnos y empuja al Executor con evidence ("ya falló esto en focusnow", "llevas 12 turnos sin grader en fase 5 in_progress").
- **Capa de auto-mejora**: las `reasoning_traces` capturan calibración + alternativas en gates densos. Dan corpus para que el doctor detecte razonamiento defectuoso (no solo errores) y para SFT futuro de un modelo APEX-tuned (alineado con la visión 2026 de Vicente).

### 0.3 Lecciones cross-project a respetar (inyectadas por session-start hook)

Errores documentados en otros proyectos que NO se deben repetir:

1. **focusnow (critical)** — Asumí stack dependiente de plataforma sin verificar. Lección: SIEMPRE `uname -s` antes de proponer stack. Vicente está en **Linux**.
2. **focusnow (critical)** — Emojis como iconos UI. Lección: NUNCA emojis. Lucide/Phosphor/Heroicons/SVG custom.
3. **focusnow (critical)** — Frontend con datos mock declarado completado. Lección: NUNCA cerrar fase frontend con mock. Conectar al backend real, verificar E2E ANTES de presentar.
4. **focusnow (critical)** — No git init durante fases 5-11. Lección: `git init` + primer commit DEBE ser primer sub-paso de Fase 5, ANTES de escribir código. Conventional commits cada cambio significativo.
5. **tfg-tutor-virtual (critical)** — Datos detectados por agente upstream no se propagan al downstream. Lección: en arquitecturas multi-agente con orquestador, los datos detectados por un agente DEBEN fluir explícitamente en el `context` compartido, no asumirse desde otro path.

Estos 5 patrones son exactamente los que el Advisor debe detectar via `apex_search_cross_project` y emitir como `cross_project_error` advice cards.

### 0.4 Reglas de trabajo no negociables

- Sprint por sprint, verificar antes de cerrar
- NUNCA emojis, ni en código ni en UI ni en prose
- Español con tildes y eñes correctas
- No datos mock en fases que se declaran completadas
- `wiki/decisions/` (formato `YYYY-MM-DD-slug.md`) como ADRs canónicos
- Ralph-loop pattern para auto-mejora, no implementaciones half-done

---

## 1. Confirmación MAX vs API (la pregunta clave)

**Sí, todo el Advisor corre bajo MAX. NUNCA via API directa.**

### Distinción crítica

| Mecanismo | Billing | Cuándo |
|-----------|---------|--------|
| `Task(subagent_type="apex-advisor", prompt=...)` | **MAX** (subagent budget) | Main loop dispara subagent dentro de la sesión activa. Los 5 roles de Sprint 12 (`apex-architect`, etc.) ya funcionan así |
| MCP tool / hook → `api.anthropic.com/v1/messages` con `claude-opus-4-7` | **API billing** (sale de MAX) | Requiere `ANTHROPIC_API_KEY`. Lo evitamos por completo |

### Diseño que garantiza MAX

El hook `advisor-trigger.py` **NO llama al modelo**. Solo:
1. Construye el bundle (~1800 tokens) leyendo `context.db`
2. `INSERT advisor_reviews(status='pending')`
3. Inyecta a stderr un `<system-reminder>` imperativo: "Invoca `Task(subagent_type='apex-advisor', prompt=<bundle>)` ahora. review_id=N. MAX, no API."

El main loop (Executor) ve el reminder en el siguiente UserPromptSubmit, dispara el `Task`. El subagent corre **dentro de la misma sesión MAX**. Cuando termina, sus `apex_record_advice(...)` quedan en BD. El hook `advice-injector.py` los inyecta como instrucciones del usuario en el siguiente turno.

### Caveats reales

- MAX tiene rate-limits por hora y semana. Estimación con circuit breaker activo: 5-6 reviews × 4K tokens Opus = ~24K/sesión. Con 4-5 sesiones densas/día = 500-600K tokens Opus/semana. Asumible para MAX 200, ajustado para MAX 100.
- Si el `Task` falla (subagent error), el review queda `status='error'`. El hook NO retry; el doctor (en S16+) puede detectar runs huérfanos.

---

## 2. Arquitectura del Advisor (el motor)

### 2.1 Flujo extremo a extremo

```
[Executor: Claude Code main, Sonnet]
    │
    ├─ tool calls → tool_call_log (ya existe, S11.2)
    │       │
    │       contador en project_meta.advisor_tool_count
    │
    ├─ tras N=8 calls O force_trigger
    │       │
    │       ▼
    │  [Hook PostToolUse: advisor-trigger.py]
    │       │
    │       ├─ should_run() aplica throttle + circuit breaker
    │       ├─ build_bundle(session_id) → ~1800 tokens (hard cap 2500)
    │       ├─ INSERT advisor_reviews(status='pending', trigger_kind=...)
    │       └─ stderr: <system-reminder>imperativo invocar Task</system-reminder>
    │
    ├─ siguiente turno → Executor lee reminder, dispara Task
    │       │
    │       ▼
    │  [Subagent apex-advisor: Opus, on-demand, MAX]
    │       │ tools: apex_get_context, apex_search,
    │       │        apex_search_cross_project, apex_record_advice
    │       │
    │       ├─ lee bundle del prompt
    │       ├─ consulta hub.db cross-project si aplica
    │       ├─ emite 0-3 cards via apex_record_advice(...)
    │       └─ termina, retorna summary al Executor
    │
    ├─ siguiente UserPromptSubmit
    │       │
    │       ▼
    │  [Hook UserPromptSubmit: advice-injector.py]
    │       │
    │       └─ lee advisor_advice WHERE review_id=N AND dismissed=0
    │          inyecta como additionalContext con prioridad por severity
    │          critical → prepend con BLOQUEANTE
    │
    └─ Executor aplica las cards O llama apex_dismiss_advice(id, reason)
        (dismissed_reason obligatorio para auditar el olvido voluntario)
```

### 2.2 `lib/advisor.py` — funciones clave

```python
# Constantes de pacing
ADVISOR_DEFAULT_INTERVAL = 8           # tool calls entre reviews
ADVISOR_BACKOFF_INTERVAL = 16          # cuando empty_streak >= 3
ADVISOR_EMPTY_STREAK_THRESHOLD = 3
ADVISOR_BUNDLE_MAX_TOKENS = 2500       # hard cap, summarize si supera
ADVISOR_MIN_CALLS_BEFORE_FIRST = 3     # evita review en sesiones cortas
ADVISOR_FORCE_TRIGGERS = {
    'apex_set_phase',                          # ignora throttle
    'apex_grader_evaluate.should_block=1',     # solo verdicts bloqueantes
    'apex_add_error.severity=critical',
    'apex_add_error.severity=high',
}

def build_bundle(session_id: str) -> dict:
    """Compone contexto compacto. Hard cap 2500 tokens.

    Returns:
        {
            'phase': {'current': N, 'duration_minutes': X, 'status': 'in_progress'},
            'recent_decisions': [...],   # últimas 3, rationale resumido
            'blocking_verdicts': [...],  # del grader
            'recent_traces': [...],      # últimas 5 reasoning_traces
            'recent_tool_calls': [...],  # últimos 20, signature compacta
            'cross_project_errors': [...],  # apex_search_cross_project top 3
            'frictions': [...],          # de /insights si hay
        }
    """

def should_run(session_id: str, force: bool = False) -> tuple[bool, str]:
    """Devuelve (run, reason). Aplica throttle + circuit breaker.
    Lee project_meta.advisor_tool_count, .advisor_empty_streak,
    .advisor_current_interval."""

def record_review(session_id, trigger_kind, bundle_size_tokens) -> int:
    """INSERT advisor_reviews, devuelve review_id."""

def record_advice(review_id, kind, severity, title, body, evidence_refs):
    """INSERT advisor_advice. Idempotente por (review_id, kind, title) UNIQUE."""

def dismiss_advice(advice_id, reason):
    """UPDATE dismissed=1, dismissed_reason=reason. Razón obligatoria."""

def get_active_advice(session_id) -> list[dict]:
    """Para advice-injector. Filtra NOT dismissed AND review reciente (<2h)."""
```

### 2.3 Subagent `apex-advisor` — frontmatter + system prompt

`~/.claude/agents/apex-advisor.md` (instalado via `apex_install_roles` extendido):

```yaml
---
name: apex-advisor
description: Asesor on-demand de procesos APEX. Lee shared context (fase, decisions, verdicts, trazas, errores cross-project) y emite 0-3 advice cards estructuradas para evitar olvido de tools, repetición de errores cross-project, deriva de fase, o handoffs huérfanos. NO escribe código, NO ejecuta. <example>Context: Executor en fase 5 in_progress, 12 tool calls sin grader, error similar en focusnow. user: <hook trigger> assistant: Invocaré apex-advisor con el bundle</example>
tools: mcp__apex__apex_get_context, mcp__apex__apex_search, mcp__apex__apex_search_cross_project, mcp__apex__apex_record_advice
model: opus
color: yellow
---
```

System prompt (~600 tokens, esquema):

1. **Rol**: asesor procedural, NO ejecutas, NO propones código, NO arquitectura.
2. **Reglas absolutas**:
   - Máximo 3 advice cards por review. Si nada cualifica → 0 cards (es válido).
   - Cada card lleva `evidence_refs` concretos (decision_id, error_id, trace_id, cross_project_path). NO inventas refs.
   - Solo 5 `kind`: `forgotten_tool`, `cross_project_error`, `phase_drift`, `recommend_skill_handoff`, `grader_overdue`.
3. **Severity**: `info` (recordatorio), `warn` (riesgo claro), `critical` (bloqueante de proceso).
4. **Output**: una llamada a `apex_record_advice(...)` por card. Final: "Emití N cards: [...]" o "0 cards. Sin alertas."
5. **Anti-patrones que invalidan tu output**: card sin evidence_refs, sugerir código, opinar sobre stack, más de 3 cards, terminar sin llamar `apex_record_advice` cuando sí hay alertas.

---

## 3. reasoning_traces (el combustible)

### 3.1 Filosofía

Trazas como **insumo del Advisor + corpus para SFT futuro**, no como log pasivo. Solo en **gates densos**. Inspiración Hermes 3 pero con 4 categorías iniciales (no 15).

### 3.2 Categorías iniciales (4 de 15 Hermes)

Las que más mapean al dolor cross-project documentado:

| Categoría | Por qué empezar aquí |
|-----------|---------------------|
| `cascading_failure_recovery` | El doctor A1 (recurrencia de errores) y A2 (grader_block_patterns) ya detectan el síntoma. Las trazas capturan el razonamiento previo al fallo |
| `socratic_self_correction` | Mapea a fase 0 (skill `socratic`) y a override de decisiones invalidadas. El bug "frontend mock declarado completo" sería una falla aquí |
| `multi_agent_coordination` | Sprint 12 introdujo 5 roles. Las trazas en gates de fase 2 (architect) y fase 8 (review) capturan cómo el orquestador decide delegar |
| `long_horizon_consequences` | Decisiones de fase 1-3 cuyo coste se ve en fase 11. Mapea al grader y al portfolio bridge |

Las 11 restantes (epistemic_self_awareness, adversarial_robustness, multi_turn_negotiation, consequential_engineering, moral_hazard_recognition, embodied_somatic_intelligence, narrative_causality, sysadmin_blast_radius, data_science_accountability, frontend_ux_consequence, devops_cost_awareness) entran en S16+ con datos reales.

### 3.3 Gates donde se capturan trazas

| Gate | Categoría sugerida | Trazas esperadas/proyecto |
|------|-------------------|--------------------------|
| Cierre fase 0 (socrática) | `socratic_self_correction` | 1-2 |
| Cierre fase 1 (alcance) | `long_horizon_consequences` | 1 |
| Cierre fase 2 (diseño) | `multi_agent_coordination` | 1-2 |
| Cierre fase 3 (spec) | `socratic_self_correction` | 1 |
| Cierre fase 8 (review) | `cascading_failure_recovery` | 1-2 |
| Cierre fase 10 (security) | `cascading_failure_recovery` | 1 |
| Verdict bloqueante grader | `cascading_failure_recovery` | 1 |
| Override de decisión (`apex_invalidate_decision`) | `socratic_self_correction` | 1 |
| Doctor proposal aceptada | `multi_agent_coordination` | 1 |

**Total esperado: ~18-22 trazas densas/proyecto**, no las 28 fijas que mencionamos al inicio. Mejor que ruidosas.

### 3.4 `lib/reasoning_traces.py`

```python
TRACE_CATEGORIES_V1 = {
    'cascading_failure_recovery',
    'socratic_self_correction',
    'multi_agent_coordination',
    'long_horizon_consequences',
}

def log_trace(
    session_id: str,
    phase: int | None,
    category: str,
    gate_kind: str,    # 'phase_close', 'grader_blocking', 'doctor_proposal', 'override'
    deliberation: str,                    # 200-2000 chars
    calibration_confidence: float,        # 0.0-1.0
    calibration_text: str,                # "70% seguro porque X; 30% restante es Y"
    alternatives_considered: list[dict],  # [{'option': '...', 'rejected_because': '...'}]
) -> int:
    """INSERT reasoning_traces. Valida category in TRACE_CATEGORIES_V1."""

def get_recent(session_id: str, limit: int = 5) -> list[dict]:
    """Para build_bundle del Advisor."""

def export_sharegpt(project_path: str, output_path: str):
    """Exporta corpus en formato ShareGPT compatible para SFT/DPO.
    Cada traza → conversation:
      {from: human, value: <gate context>},
      {from: gpt, value: deliberation+calibration+alternatives}.
    Compatible con pipelines de OusiaResearch, axolotl, llamafactory."""

def prompt_for_trace(category: str, gate_kind: str) -> str:
    """Devuelve instrucción imperativa para inyectar a additionalContext.
    Ejemplo:
    'Antes de cerrar fase 8, registra una traza con apex_log_trace(
       category=cascading_failure_recovery,
       gate_kind=phase_close,
       deliberation=<200-500 palabras sobre cómo llegaste a esta decisión>,
       calibration_confidence=<0-1>,
       calibration_text=<por qué no estás 100%>,
       alternatives_considered=<JSON con 1-3 alternativas y por qué las descartaste>
    ).'"""
```

### 3.5 Hook `trace-prompt.py` (PostToolUse, filtrado)

Triggers explícitos:
- `apex_set_phase` con `next_phase in {1, 2, 3, 4, 9, 11}` (cierre de fase deliberativa)
- `apex_grader_evaluate` con `should_block=1`
- `apex_doctor_run` con `proposals_count >= 1`
- `apex_invalidate_decision` (override)

Inyecta el `prompt_for_trace(category, gate_kind)` correspondiente como instrucción imperativa al Executor. Timeout 1s, no bloqueante.

---

## 4. /prototype skill (la herramienta nueva de Pocock)

### 4.1 Concepto adaptado

Pocock observa que **specs en prosa son malas para business logic con estados**. Una **TUI ejecutable** que modele estados y transiciones permite "atajar" a estados profundos sin recorrer la cadena → feedback más rico que leyendo prosa.

Vicente reconoce que es un punto que no había considerado. La oportunidad es ortogonal a las skills que ya tiene: APEX hoy genera DESIGN.md (S10), specs (fase 3), wiki/decisions/, pero no prototipos ejecutables de business logic.

### 4.2 Adaptación APEX (scaffold en S15, TUI completa en S16)

**S15 entrega**: scaffold + tool de init. NO la interactividad TUI completa.

`skills/prototype/SKILL.md`:

```yaml
---
name: prototype
description: Prototipa lógica de negocio compleja como máquina de estados ejecutable (TUI Python con Textual). Mejor que prosa para validar transiciones, edge cases, y reglas de negocio. Se invoca cuando hay >5 reglas de negocio, transiciones de estado no triviales, o cuando el Advisor emite recommend_skill_handoff(target=prototype). Genera un .py ejecutable + schema de estados commiteado a wiki/concepts/.
---
```

Cuerpo del skill (estructura):

1. **Cuándo invocar** (4 triggers concretos):
   - Spec con >5 reglas de negocio
   - Decision con `complexity_score` alta y solo prosa en rationale
   - Tests fallando que apuntan a transiciones mal entendidas
   - Advisor emite `recommend_skill_handoff(target='prototype')`
2. **Pasos**:
   - `apex_prototype_init(feature_name, states, transitions, initial_state)` genera scaffold
   - Definir estados (lista) y transiciones (estado_origen, evento, estado_destino, guardas)
   - Generar TUI Textual con `bindings` para cada transición (atajos teclado a estados profundos)
   - Validar reachability + dead states con check estático
   - Commit a `.apex/prototypes/<feature>.py`
   - Sincronizar a `wiki/concepts/<feature>-state-machine.md` con diagrama Mermaid
3. **Anti-patrones**: prototipar cuando la lógica cabe en 3 reglas, no validar reachability, omitir guards.
4. **Puente APEX**: el Advisor lo recomienda; el grader (post-implementación) verifica que las transiciones del prototype quedaron honored en el código real.

### 4.3 Tool `apex_prototype_init`

```python
def apex_prototype_init(
    feature_name: str,
    states: list[str],
    transitions: list[dict],
    # [{'from': 'draft', 'event': 'submit', 'to': 'review', 'guard': 'has_required_fields'}]
    initial_state: str,
) -> dict:
    """Genera scaffold:
    - .apex/prototypes/<feature_name>.py (Textual TUI base, listo para correr)
    - wiki/concepts/<feature_name>-state-machine.md (Mermaid + reglas)
    - INSERT state_machines (para que el grader lo verifique luego).

    Returns: {'tui_path': ..., 'wiki_path': ..., 'machine_id': N}"""
```

S15 NO implementa: atajos a estados profundos, replay de transiciones, fuzzing de guards. Eso es S16.

---

## 5. skill_handoff (el puente del flujo Pocock/Ruflo)

### 5.1 Flujo objetivo

```
grill-with-docs → handoff → prototype → handoff de vuelta → grill-with-docs
                                  ↓
                              to-prd → to-issues → sandcastle → improve-architecture
```

Cambio de modo **dentro de la sesión**, sin perder context, registrado como traza.

### 5.2 Tools

```python
def apex_handoff_skill(
    from_skill: str,
    to_skill: str,
    reason: str,
    snapshot: dict,
    # estado a preservar: archivos abiertos, decisiones tentativas, preguntas pendientes
) -> dict:
    """INSERT skill_handoffs. Devuelve instrucción para main loop:
    'Invoca skill <to_skill> ahora. Snapshot disponible vía
     apex_resume_skill_handoff(handoff_id=N).'"""

def apex_resume_skill_handoff(handoff_id: int) -> dict:
    """Devuelve snapshot + instrucción:
    'Vuelve a skill <from_skill>. Aplica resultado del modo destino: <result_summary>.'
    UPDATE skill_handoffs SET returned_at=now()."""
```

### 5.3 Detección de huérfanos

El Advisor lee `skill_handoffs WHERE returned_at IS NULL AND created_at < now()-1800` y emite `phase_drift` card por handoffs huérfanos (>30 min sin volver al modo origen).

---

## 6. Schema completo (5 tablas nuevas)

```sql
CREATE TABLE advisor_reviews (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  triggered_at REAL NOT NULL,
  trigger_kind TEXT NOT NULL,        -- 'tool_count', 'phase_change', 'grader_blocking', 'manual', 'circuit_breaker_reset'
  bundle_size_tokens INTEGER,
  advice_count INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER,
  status TEXT NOT NULL                -- 'pending', 'completed', 'skipped', 'error'
);
CREATE INDEX idx_advisor_reviews_session ON advisor_reviews(session_id, triggered_at DESC);

CREATE TABLE advisor_advice (
  id INTEGER PRIMARY KEY,
  review_id INTEGER NOT NULL REFERENCES advisor_reviews(id),
  kind TEXT NOT NULL,
  -- 'forgotten_tool', 'cross_project_error', 'phase_drift', 'recommend_skill_handoff', 'grader_overdue'
  severity TEXT NOT NULL,             -- 'info', 'warn', 'critical'
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  evidence_refs TEXT,                 -- JSON array
  dismissed INTEGER NOT NULL DEFAULT 0,
  dismissed_reason TEXT,
  created_at REAL NOT NULL,
  UNIQUE(review_id, kind, title)
);

CREATE TABLE reasoning_traces (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  phase INTEGER,
  category TEXT NOT NULL,             -- TRACE_CATEGORIES_V1
  gate_kind TEXT NOT NULL,            -- 'phase_close', 'grader_blocking', 'doctor_proposal', 'override'
  deliberation TEXT NOT NULL,
  calibration_confidence REAL,
  calibration_text TEXT,
  alternatives_considered TEXT,       -- JSON
  created_at REAL NOT NULL
);
CREATE INDEX idx_traces_session_phase ON reasoning_traces(session_id, phase);
CREATE INDEX idx_traces_category ON reasoning_traces(category);

CREATE TABLE skill_handoffs (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  from_skill TEXT NOT NULL,
  to_skill TEXT NOT NULL,
  reason TEXT NOT NULL,
  snapshot TEXT NOT NULL,             -- JSON
  result_summary TEXT,
  created_at REAL NOT NULL,
  returned_at REAL
);

CREATE TABLE state_machines (
  id INTEGER PRIMARY KEY,
  feature_name TEXT NOT NULL,
  states TEXT NOT NULL,               -- JSON array
  transitions TEXT NOT NULL,          -- JSON array
  initial_state TEXT NOT NULL,
  tui_path TEXT NOT NULL,
  wiki_path TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(feature_name)
);

-- Meta para circuit breaker reusa project_meta con keys:
--   advisor_tool_count, advisor_empty_streak, advisor_current_interval, advisor_last_review_at
```

Auto-migración via `_ensure_db_schema` (ya existente, agregar las 5 tablas al `_SCHEMA` constant).

---

## 7. Tools MCP nuevas (7 → total 49)

| Tool | Argumentos | Persistencia | Quién la invoca |
|------|------------|--------------|-----------------|
| `apex_advisor_review` | `force, trigger` | `advisor_reviews` | Hook o user manual |
| `apex_record_advice` | `review_id, kind, severity, title, body, evidence_refs` | `advisor_advice` | Subagent apex-advisor |
| `apex_dismiss_advice` | `advice_id, reason` | UPDATE | Executor cuando ignora |
| `apex_log_trace` | `category, deliberation, calibration_*, alternatives` | `reasoning_traces` | Executor en gates |
| `apex_handoff_skill` | `from, to, reason, snapshot` | `skill_handoffs` | Executor o Advisor recomendado |
| `apex_resume_skill_handoff` | `handoff_id` | UPDATE | Executor al volver |
| `apex_prototype_init` | `feature, states, transitions, initial_state` | `state_machines` + ficheros | Skill /prototype |

Total tools tras S15: **49** (era 42).

---

## 8. Hooks nuevos (3)

### 8.1 `.claude/hooks/advisor-trigger.py` (PostToolUse)

```
- Cuenta tool calls en project_meta.advisor_tool_count
- Si should_run() returna True:
    * build_bundle(session_id) → ~1800 tokens
    * INSERT advisor_reviews(status='pending')
    * stderr: <system-reminder> imperativo invocar Task(subagent_type='apex-advisor', prompt=<bundle>)
- Force triggers: tras apex_set_phase, apex_grader_evaluate(should_block=1),
  apex_add_error(severity in [critical, high])
- Timeout wall-clock 2s, NO bloqueante
- Si falla: stderr aviso, dejar seguir
```

### 8.2 `.claude/hooks/advice-injector.py` (UserPromptSubmit)

```
- Lee advisor_advice activas (NOT dismissed, review <2h)
- Inyecta a additionalContext con prioridad por severity
- Si hay critical: prepend con
  <system-reminder>BLOQUEANTE: aplicar advice id=N antes de continuar.
  Si no aplica, llama apex_dismiss_advice(N, reason="<motivo claro>").</system-reminder>
- Si tras 2 turnos siguen sin atenderse → escala el reminder (mantener visible)
- Timeout 1s, NO bloqueante
```

### 8.3 `.claude/hooks/trace-prompt.py` (PostToolUse, filtrado)

```
- Triggers: apex_set_phase next_phase in {1,2,3,4,9,11},
  apex_grader_evaluate(should_block=1),
  apex_doctor_run(proposals_count>=1),
  apex_invalidate_decision
- Inyecta prompt_for_trace(category, gate_kind) como instrucción imperativa
- Timeout 1s, NO bloqueante
```

Total hooks tras S15: **10** (era 7: session-start, design-lint, phase-gate, context-watch, post-tool-archive, skill-forge-watch, end-of-day-doctor).

---

## 9. Tasks descompuestas (S15.1 - S15.9)

| Task | Alcance | Tests | LoC aprox |
|------|---------|-------|-----------|
| **S15.1** Schema migration (5 tablas + claves project_meta) | Extender `_ensure_db_schema` en lib/context_db.py | 8 | ~150 |
| **S15.2** `lib/advisor.py` (build_bundle, should_run, record_*, dismiss, get_active) | Throttle + circuit breaker | 18 | ~400 |
| **S15.3** `lib/reasoning_traces.py` (log, get_recent, export_sharegpt, prompt_for_trace) | 4 categorías iniciales | 12 | ~250 |
| **S15.4** Tools MCP (7 nuevas) | Wiring en mcp/apex_server.py | 14 | ~300 |
| **S15.5** Subagent `apex-advisor` | .md + extender `apex_install_roles` | 4 | ~100 |
| **S15.6** Hooks (advisor-trigger, advice-injector, trace-prompt) | UserPromptSubmit + PostToolUse | 6 | ~250 |
| **S15.7** Skill /prototype scaffold + tool `apex_prototype_init` | SKILL.md + scaffold Textual | 5 | ~200 |
| **S15.8** Wiring flujo Pocock en commands/apex.md | grill→handoff→prototype→prd→issues→improve-arch | 3 | ~100 (md) |
| **S15.9** Documentación CLAUDE.md + memoria APEX | — | 0 | ~80 |

**Total: ~70 tests nuevos. ~1830 LoC. Suite final esperada: 466 verde** (era 396 antes de S15).

### Orden de implementación recomendado

1. **S15.1** schema — bloqueante de todo
2. **S15.2 + S15.3** en paralelo (libs core)
3. **S15.4** tools — depende de libs
4. **S15.5** subagent — depende de tools (necesita `apex_record_advice`)
5. **S15.6** hooks — depende de tools y subagent
6. **S15.7** prototype — paralelizable con S15.6
7. **S15.8** + **S15.9** wiring + docs al final

### TDD obligatorio

Aplicar la skill `tdd` (S14): red-green-refactor estricto, una rebanada vertical cada vez. Para cada subtarea: escribir test que falla → mínimo código que pasa → refactor sin romper.

---

## 10. Tradeoffs explícitos y riesgos

### Tradeoff principal del sprint

**Beneficio:**
- El Executor deja de olvidar. Las herramientas que ya construiste (42 tools, 23 skills) empiezan a invocarse cuando toca porque hay un advisor leyendo evidence y empujando.
- Las trazas dan corpus para SFT futuro y para que el doctor detecte razonamiento defectuoso (no solo errores).
- /prototype añade una herramienta ortogonal (validar business logic ejecutable, no en prosa).

**Coste:**
- Sprint pesado: 5 tablas, 7 tools, 3 hooks, 1 subagent, 1 skill nueva.
- Latencia: cada review añade 5-15s al turno donde se dispara.
- Tokens MAX: ~24-30K tokens Opus/sesión densa (asumible).
- Riesgo de ruido: si las cards son malas, el Executor las dismissea — y queda log auditable, pero pierdes confianza.

### Decisiones de diseño con sus alternativas

| Decisión | Alternativa rechazada | Razón |
|----------|----------------------|-------|
| Subagent vía Task | API directa Anthropic | MAX-friendly, sin `ANTHROPIC_API_KEY` requerido |
| 4 categorías de trazas | 15 categorías Hermes | Empezar denso, expandir con datos reales en S16+ |
| Trazas solo en gates | Trazas por turno | ~20 trazas densas > 100 ruidosas |
| /prototype scaffold | Implementación TUI completa | No infles el sprint; TUI real va en S16 |
| Modelo Opus | Sonnet | Calidad >> velocidad cuando solo se invoca 5-6×/sesión |
| Threshold 8 calls | 5 ó 12 | Tradeoff entre frescura y coste; 8 deja margen al circuit breaker |

### Riesgos a mitigar

- **R1**: Bundle del Advisor explota → hard cap 2500 tokens, summarize con `lib/token_filter.py` (S9.2).
- **R2**: Cards ignoradas en silencio → `dismissed_reason` obligatorio, doctor A7 (futuro) detecta dismiss recurrente.
- **R3**: Subagent en loop → tools whitelist restringida (NO `Task`, NO `Bash`), system prompt explícita "máx 3 cards, terminar".
- **R4**: Hook se dispara en sesiones cortas → `ADVISOR_MIN_CALLS_BEFORE_FIRST=3`.
- **R5**: El reminder del hook se ignora en la práctica → escalar a `<system-reminder>BLOQUEANTE</system-reminder>` cuando hay cards `critical` sin atender. Si tras 2 turnos siguen sin atenderse, prepend al additionalContext del UserPromptSubmit hasta que se atiendan o se dismisseen.

### Lo que el sprint NO hace (deuda explícita para S16+)

- TUI real de /prototype (atajos a estados profundos, replay, fuzzing)
- Promoción automática de trazas a memoria permanente (dreaming)
- Embeddings locales para búsqueda semántica en trazas
- Feedback loop del usuario sobre advice cards (rating "útil/no útil")
- Categorías 5-15 de trazas (faltan 11 de las 15 Hermes)
- Auto-export de trazas a HuggingFace para corpus público (CC BY-NC 4.0 estilo OusiaResearch)

---

## 11. Cómo arrancar la sesión limpia

### Estado al cerrar la sesión origen

- Sesión origen: `b79459e8-d02`, ~74.5% de contexto consumido (~149K/200K tokens)
- Handoff serializado en `.apex/handoff/b79459e8-d02.md` (vía `apex_resume_session`)
- Blueprint persistido en `.apex/sprints/sprint-15-advisor-blueprint.md` (este archivo)
- BD `apex/.apex/context.db` con estado actual del proyecto APEX
- Suite tests: 396 verde antes del sprint
- Branch: `main` (commits c222df1, 99802a7, 9e52448, 40cea00, 11e995c — Sprint 14 cerrado)
- Untracked: `.apex/doctor/`, `apex_audit.jsonl`, `apex_audit.md`, `apex_audit.py` (revisar si se mergean o se descartan en sesión nueva)

### Pasos para la sesión nueva

```bash
# En la sesión nueva, primer prompt:
apex_resume_session(session_id="b79459e8-d02")
Read .apex/sprints/sprint-15-advisor-blueprint.md
```

Después:

> "Ejecuta S15.1 (schema migration de las 5 tablas nuevas) siguiendo el blueprint en `.apex/sprints/sprint-15-advisor-blueprint.md`. Aplica la skill `tdd` de S14 (red-green-refactor estricto). No avanzar a S15.2 hasta que los 8 tests de S15.1 pasen verde."

### Verificaciones previas a S15.1

1. `uname -s` (debe decir Linux — confirmación lección focusnow)
2. `ls ~/.claude/agents/` (verificar que los 5 agents de S12 están instalados)
3. `cat ~/.claude/settings.json | jq '.hooks'` y `cat .claude/settings.json | jq '.hooks'` (verificar el bug del hook context-watch reportado por Vicente — si está solo a nivel proyecto, ese es el bug)
4. `PYTHONPATH=lib .venv/bin/pytest tests/ -v --tb=short -x` (baseline 396 verde)
5. `git status` (revisar untracked: `.apex/doctor/`, `apex_audit.jsonl`, `apex_audit.md`, `apex_audit.py` — decidir si commit, .gitignore, o eliminar)

### Criterio de éxito del sprint

- Suite ~466 verde
- 7 tools nuevas funcionando (probar cada una con caso happy y caso error)
- Subagent `apex-advisor` instalado en `~/.claude/agents/` y disparable via `Task`
- Hooks `advisor-trigger`, `advice-injector`, `trace-prompt` registrados y testeados
- Skill `/prototype` scaffold operativo (no TUI completa)
- Demo end-to-end: en un proyecto de prueba, llevar 10 tool calls sin grader → ver el advisor disparar → ver advice card "grader_overdue" inyectada → aplicarla y verificar que `apex_grader_evaluate` se llama → verificar que la review queda con advice_count=1 y status='completed' en BD
- CLAUDE.md actualizado con sección Sprint 15
- Memoria APEX actualizada con el patrón Advisor

---

## 12. Notas finales

- Si el sprint se hace muy pesado en una sola sesión, **partirlo en 15.A (advisor + traces, S15.1-S15.6) y 15.B (prototype + wiring, S15.7-S15.9)**. Esto es legítimo y respeta la regla "sprint por sprint, verificar antes de cerrar".
- Antes de empezar S15.1, considerar correr `apex_doctor_run(force=True, trigger='manual')` para limpiar señales pendientes y arrancar con BD limpia.
- Tras S15.5 (subagent instalado), el primer test real es invocarlo manualmente: `Task(subagent_type='apex-advisor', prompt='<bundle de prueba>')` y verificar que devuelve cards estructuradas via `apex_record_advice`.
- Confirmar con Vicente al cerrar S15.6 (hooks) si el reminder imperativo del `advisor-trigger.py` realmente fuerza al main loop a invocar el Task. Si no, escalar a `<system-reminder>` con tag más fuerte y prepend en cada UserPromptSubmit hasta que se invoque.

---

**Fin del blueprint. Auto-contenido. Listo para continuar en sesión limpia.**
