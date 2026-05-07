# Sprint 16 — Advisor Feedback Loop (rating implícito vía facets + escape hatch manual)

> Estado: blueprint v2 (propuesta). Reemplaza la v1 de este mismo archivo.
> Predecesor obligatorio: Sprint 15 cerrado (commits `fa65891` + `33d59fc`).
> Sucesor sugerido: S17 (VirtualFS) — abrir solo tras cerrar S16.

---

## 0. Contexto y cambio de enfoque respecto a v1

S15 dejó al Advisor con constantes calibradas a ojo (`MIN_CALLS=8`,
`BACKOFF=16`, `MAX_CARDS=3`, umbral circuit breaker 3 vacíos) y sin
canal de retorno. La pregunta clave: ¿cómo medir si las cards son
útiles sin obligar a Vicente a ratearlas una por una?

La **v1** de este blueprint (commit `dd61083`) propuso un sistema de
rating explícito con tabla `advice_ratings` y tres niveles
(`useful`/`not_useful`/`false_positive`). Tras revisar `apex_doctor`
A5/A6 (Sprint 13.9) y observación #6681 (100 sesiones de facets ya
acumuladas), se identificó que existe ya infraestructura de rating
**implícito** en `~/.claude/usage-data/facets/`. La **v2** invierte el
diseño: rating implícito como camino principal (cero fricción para el
usuario), rating manual como escape hatch puntual.

**Razón del cambio**: Vicente tiene TDAH y prefiere iterar sobre tareas
concretas, no detenerse cada 8 calls a ratear una card. Además, ya hay
100 sesiones de facets acumuladas — material suficiente para arrancar
el tuning sin esperar a ratear nada.

---

## 1. Datos disponibles desde Sprint 13.9

`lib/usage_data_reader.py` ya expone:

- `iter_meta(project_path) -> Iterator[UsageMeta]`: sesiones con
  `start_time`, `duration`, `tool_counts`, `tool_errors`,
  `tool_error_categories`, `lines_added/removed`.
- `iter_facets(session_ids) -> Iterator[UsageFacets]`: con `outcome`
  (`fully_achieved` | `mostly_achieved` | `partially_achieved` |
  `not_achieved` | `unclear_from_transcript`), `claude_helpfulness`
  (`essential` | `very_helpful` | `moderately_helpful` |
  `slightly_helpful` | `unhelpful`), `user_satisfaction_counts`
  (`satisfied` | `dissatisfied` | `frustrated`), `friction_counts`
  (buggy_code, wrong_approach, misunderstood_request, etc.).
- `find_session_for_timestamp(ts, project_path, slack_minutes=5)`:
  asocia un timestamp con la sesión de Claude Code que lo contenía.

`apex_doctor` A5 ya cruza `grader_verdicts` con facets vía esta
heurística temporal. **S16 reusa el patrón** sobre `advisor_advice`.

---

## 2. Schema (1 tabla nueva)

```sql
CREATE TABLE advice_outcomes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  advice_id     INTEGER NOT NULL,
  session_id    TEXT,                      -- session_id de facets si hay match
  assoc_method  TEXT    NOT NULL CHECK (assoc_method IN
                  ('temporal', 'manual')),
  -- Datos del facet asociado (NULL si assoc_method='manual'):
  facet_outcome      TEXT,                 -- fully_achieved | mostly_achieved | ...
  facet_helpfulness  TEXT,                 -- essential | very_helpful | ...
  facet_satisfaction TEXT,                 -- satisfied | dissatisfied | frustrated | mixed
  friction_keys      TEXT,                 -- JSON list de keys con count>0
  -- Rating inferido o manual:
  inferred_rating  TEXT NOT NULL CHECK (inferred_rating IN
                     ('useful', 'not_useful', 'unclear')),
  manual_reason    TEXT,                   -- requerido si assoc_method='manual'
  computed_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (advice_id) REFERENCES advisor_advice(id) ON DELETE CASCADE,
  UNIQUE (advice_id, assoc_method)         -- max 1 implicit + 1 manual por advice
);
CREATE INDEX idx_advice_outcomes_advice  ON advice_outcomes(advice_id);
CREATE INDEX idx_advice_outcomes_session ON advice_outcomes(session_id);
CREATE INDEX idx_advice_outcomes_rating  ON advice_outcomes(inferred_rating);
```

```sql
CREATE TABLE advisor_tuning_history (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  applied_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  category      TEXT    NOT NULL,           -- forgotten_tool | phase_drift | ...
  constant_name TEXT    NOT NULL,           -- e.g. 'min_calls_between_reviews'
  old_value     REAL    NOT NULL,
  new_value     REAL    NOT NULL,
  trigger_n_outcomes INTEGER NOT NULL,
  fp_rate_before     REAL,
  reason        TEXT,
  source        TEXT NOT NULL DEFAULT 'auto'  -- auto | manual_override
);
```

Auto-migración vía `_ensure_db_schema` (mismo patrón que S15.A).

**Migración de constantes**: las constantes hardcoded en `lib/advisor.py`
se persisten en `project_meta.advisor_constants` (JSON). Si la fila
no existe, fallback a defaults. No se rompe BD existente.

---

## 3. Heurística de inferencia de rating

Para cada advice en `advisor_advice` sin outcome computado:

1. Localizar la sesión de Claude Code que contenía `advice.created_at`
   vía `find_session_for_timestamp`.
2. Si no hay match (sesión externa, facet no escrito todavía,
   `/insights` no corrió): **no insertar** outcome. Esperar a la
   siguiente computación.
3. Si hay match, leer el facet de esa sesión.
4. Calcular `inferred_rating`:

| Condición | Rating |
|-----------|--------|
| `outcome in {not_achieved, partially_achieved}` O `helpfulness in {unhelpful, slightly_helpful}` O `satisfaction in {dissatisfied, frustrated}` | `not_useful` |
| `outcome in {fully_achieved, mostly_achieved}` Y `helpfulness in {very_helpful, essential, moderately_helpful}` Y `satisfaction not in {dissatisfied, frustrated}` | `useful` |
| Resto (incluido `unclear_from_transcript`) | `unclear` |

5. Insertar fila en `advice_outcomes` con `assoc_method='temporal'`.

**Limitación conocida (causalidad débil)**: el facet evalúa la sesión
completa, no la card específica. Una sesión "no_useful" no implica que
TODAS sus cards fueran ruidosas. **Mitigación**: solo agregar señal a
nivel de **categoría con N>=20**, nunca decidir sobre cards
individuales. La hipótesis es: si la categoría X correlaciona
sistemáticamente con sesiones malas, ajustar el throttle de X. La señal
ruidosa se cancela en el agregado.

---

## 4. Tools MCP nuevas (4 → total 53)

```python
def apex_advisor_compute_outcomes(
    lookback_days: int = 30,
    force: bool = False,
) -> dict:
    """Itera advisor_advice sin outcome computado (created_at en
    últimos lookback_days). Para cada advice, ejecuta heurística §3.
    force=True recomputa outcomes ya escritos.
    Returns: {'computed': N, 'skipped': N, 'no_facet_yet': N}"""
```

```python
def apex_rate_advice(
    advice_id: int,
    rating: str,           # 'useful' | 'not_useful' (escape hatch)
    reason: str,           # obligatorio
) -> dict:
    """ESCAPE HATCH. Inserta outcome con assoc_method='manual'.
    Útil cuando el rating implícito tarda (no hay facet aún) o cuando
    la card es tan ruidosa que merece señal explícita.
    No reemplaza al implícito: ambos coexisten en advice_outcomes
    (UNIQUE (advice_id, assoc_method)).
    Returns: {'outcome_id': N, 'auto_tuning_triggered': bool}"""
```

```python
def apex_advisor_health(
    window_days: int = 30,
) -> dict:
    """Dashboard JSON-friendly:
      - total_advice_emitted (por categoría)
      - outcomes_computed (por rating × categoría, separando temporal/manual)
      - fp_rate por categoría (None si <5 outcomes con not_useful)
      - constants_actuales (defaults vs tuned, con timestamp último tune)
      - tuning_history últimos 5
      - circuit_breaker_trips últimas 24h
      - facets_freshness: días desde el último facet leído (avisa si >7)
    """
```

```python
def apex_advisor_apply_tuning(
    dry_run: bool = True,
) -> dict:
    """Heurística determinista (§5). dry_run=True devuelve propuestas
    sin aplicar; dry_run=False UPDATE project_meta.advisor_constants
    y registra advisor_tuning_history.
    Returns: {'proposals': [{category, constant, old, new, reason}]}"""
```

---

## 5. Heurística de auto-tuning (idéntica al v1, datos distintos)

Mínimo **20 outcomes** por categoría (suma `temporal` + `manual`) antes
de tunear. Cuatro reglas deterministas:

| Categoría | Trigger | Acción |
|-----------|---------|--------|
| `forgotten_tool`         | `not_useful_rate` >40% | `min_calls_between_reviews`: 8 → 12 |
| `phase_drift`            | `not_useful_rate` >40% | `phase_drift_window_min`: 30 → 45 |
| `recommend_skill_handoff`| `not_useful_rate` >40% | `complexity_score_threshold`: 0.6 → 0.75 |
| `grader_overdue`         | `not_useful_rate` >40% | `grader_overdue_phases`: 2 → 3 |

`not_useful_rate = count(not_useful) / (count(not_useful) +
count(useful))`. Los `unclear` se excluyen del denominador (no aportan
señal). Si `unclear_rate > 50%`: el aviso aparece en `apex_advisor_health`
("la mayoría de outcomes son unclear; corre /insights más a menudo o
añade ratings manuales") pero NO se tunea.

**Cooldown 7 días** por constante (anti-oscilación). `force=True` lo
salta y registra `source='manual_override'` en history.

---

## 6. Hook (1 nuevo)

`.claude/hooks/advisor-outcome-watch.py` (UserPromptSubmit, no bloqueante).

Comportamiento:

1. Cada 10 prompts (high-water mark en
   `project_meta.last_outcome_compute_prompt`), llama a
   `apex_advisor_compute_outcomes(lookback_days=14)` con timeout
   wall-clock 3s.
2. Si `apex_advisor_apply_tuning(dry_run=True)` devuelve propuestas
   pendientes, inyecta a stdout un aviso con el comando para aplicar:
   `[advisor-tuning] 2 propuestas pendientes. Revisa con
   apex_advisor_health() y aplica con apex_advisor_apply_tuning(dry_run=False).`
3. Si `facets_freshness > 7 días`, sugiere correr `/insights`.

Coste: `iter_meta` y `iter_facets` son lecturas locales de JSON; en
benchmarks (Sprint 13.9) <50ms para 100 sesiones. Cada 10 prompts es
sobradamente conservador.

---

## 7. Skill opcional

`skills/advisor-feedback/SKILL.md` (~80 líneas) describiendo:

- Cuándo el rating implícito puede engañar (sesión globalmente buena
  con una card específicamente ruidosa).
- Cuándo usar el escape hatch `apex_rate_advice` (FP claro y
  recurrente, no esperar a que el agregado lo detecte).
- Cómo leer el dashboard.

Diferible a S16.B si el sprint se infla.

---

## 8. Tasks descompuestas (TDD obligatorio)

| ID    | Subtarea                                                    | LoC | Tests |
|-------|-------------------------------------------------------------|-----|-------|
| S16.1 | Schema (`advice_outcomes`, `advisor_tuning_history`)        | 60  | 6     |
| S16.2 | `lib/advisor_outcomes.py` + `apex_advisor_compute_outcomes` | 180 | 14    |
| S16.3 | `lib/advisor_health.py` + `apex_advisor_health`             | 100 | 8     |
| S16.4 | `lib/advisor_tuning.py` + `apex_advisor_apply_tuning`       | 130 | 12    |
| S16.5 | Migración constantes `advisor.py` → `project_meta`          | 60  | 6     |
| S16.6 | `apex_rate_advice` (escape hatch) + validación              | 60  | 6     |
| S16.7 | Hook `advisor-outcome-watch.py`                             | 80  | 4     |
| S16.8 | (Opcional) `skills/advisor-feedback/SKILL.md`               | 80  | 0     |
|       | **Total**                                                   | ~670| ~56   |

Suite objetivo: 484 → ~540 verde.

### Orden recomendado

S16.1 → S16.5 (BD + constantes preparadas) → S16.2 (motor implícito) →
S16.6 (escape hatch reusa schema de S16.1) → S16.3 (dashboard) →
S16.4 (tuning) → S16.7 (hook) → S16.8.

---

## 9. Tradeoffs explícitos

| Decisión | Alternativa | Razón |
|----------|-------------|-------|
| Path B principal (implícito) | Path A principal (manual) | Cero fricción para Vicente; aprovecha 100 sesiones acumuladas; tuning empieza inmediatamente. |
| Path A como escape hatch | Path A descartado | Hay cards que aparecen en sesiones globalmente buenas; sin manual override no se detectan nunca. |
| Causalidad débil aceptada | Asociación fina card↔task | Imposible sin instrumentación nueva. La estadística agregada (N>=20) cancela el ruido. |
| Hook cada 10 prompts | Hook tras cada advice | Coste<50ms pero acumular permite computar varias outcomes a la vez. |
| 20 outcomes/categoría | 10 ó 30 | 10 = ruido alto (1 sesión mala mueve 10%); 30 = lento; 20 = mediana FP rate estable. |
| Excluir `unclear` del denominador | Contarlos como no_useful | `unclear_from_transcript` es ausencia de señal, no señal negativa. Contarlos sesgaría a tunear de más. |
| Cooldown 7 días | 3 días | Anti-oscilación. Si una constante necesita moverse antes, `force=True` lo permite. |
| Tabla `advice_outcomes` separada | Columnas en `advisor_advice` | UNIQUE (advice_id, assoc_method) permite coexistir implícito + manual sin colisión y simplifica queries. |

---

## 10. Riesgos a mitigar

1. **/insights nunca se corre**. Sin facets nuevos, no hay outcomes. El
   dashboard avisa con `facets_freshness`. Si pasa de 14 días, el
   Advisor sigue funcionando con constantes congeladas (sin daño).
2. **Causalidad post-hoc**. Sesión mala con cards relevantes castiga
   injustamente esas cards. Mitigación: N>=20 + cooldown 7d + escape
   hatch para FPs claros.
3. **Sesgo de cobertura**. Cards en sesiones cortas (sin facet aún) no
   se cuentan. Mitigación: la heurística no asume completitud; itera
   cada 10 prompts.
4. **Outcomes obsoletos**. Si Vicente cambia de proyecto y el Advisor
   no se invoca, las constantes quedan congeladas en valores quizá ya
   inadecuados. Mitigación: `apex_advisor_health` muestra timestamp de
   última tune; si >30 días y hay outcomes nuevos, sugiere re-evaluar.
5. **Privacidad de facets**. `~/.claude/usage-data/facets/` puede
   contener fragmentos sensibles (briefs de proyectos, código). Las
   tools de S16 NO copian texto del facet a `context.db`: solo metadatos
   categóricos (outcome, helpfulness, satisfaction, friction_keys). El
   diff vs v1 es importante: v1 hubiera podido leer reasons libres del
   usuario; v2 solo lee enums.

---

## 11. Tests previstos (~56)

- `test_advice_outcomes_schema.py` (6): tabla creada, FK cascade, check
  constraints sobre rating + assoc_method, UNIQUE compuesto, índices,
  re-migración idempotente.
- `test_advisor_outcomes.py` (14): asociación temporal con facet,
  inferencia rating en cada caso (useful/not_useful/unclear), facet
  ausente devuelve `no_facet_yet`, idempotencia (no duplica), `force`
  recomputa, lookback_days filtra.
- `test_advisor_health.py` (8): BD vacía, BD con datos sintéticos,
  ventana 30d filtra, FP rate `None` si <5 not_useful, freshness
  detecta facets >7 días, defaults vs tuned se distinguen.
- `test_advisor_tuning.py` (12): no tunea con <20 outcomes, sí tunea
  con 20+ y FP>40%, cooldown 7 días bloquea, force lo salta + registra
  manual_override, dry_run no escribe, history registra cada tune.
- `test_advisor_constants_migration.py` (6): default fallback, lectura
  desde BD override, escritura idempotente.
- `test_apex_rate_advice.py` (6): inserta manual outcome, reason
  obligatorio, FK inválida raises, UNIQUE compuesto permite coexistir
  con temporal, valida rating enum.
- `test_advisor_outcome_hook.py` (4): hook lee high-water mark, no
  ejecuta antes de 10 prompts, propone tuning si dry_run encuentra
  algo, no bloquea ante timeout.

---

## 12. Cómo arrancar S16.1

```
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -q   # confirmar 484 verde
# Crear test_advice_outcomes_schema.py (red phase, 6 tests fallando)
# Aplicar migración en context_db.py (advice_outcomes + advisor_tuning_history)
# Verde: 484 → 490
```

---

## 13. Notas finales

- **Compatibilidad**: el Advisor existente sigue funcionando si la
  tabla `advice_outcomes` no existe (BD vieja sin migrar). Los hooks
  fallan gracefully.
- **Patrón replicable**: si funciona, S17+ puede aplicar el mismo
  pattern a `grader_verdicts` (rating implícito de verdicts), a
  `doctor_proposals` (rating de propuestas), a `skill_forge` (rating de
  skills auto-generadas). El bridge facets↔context.db queda
  estandarizado.
- **Datos públicos del Advisor**: `apex_advisor_health` expone solo
  enums (no texto libre), por lo que su output es publicable sin
  riesgo de filtrar contenido sensible. Útil para dogfooding y para
  documentar que APEX se mide a sí mismo.
- **Cuándo abrir S16.B (categorías Hermes 5-15)**: solo si tras 60
  días de S16 el FP rate global sigue >25%. Indica que el problema no
  está en el throttle sino en la calidad de la señal del bundle —
  necesita más categorías de trazas. Es la única condición que
  reordena el roadmap de cara a S17.
