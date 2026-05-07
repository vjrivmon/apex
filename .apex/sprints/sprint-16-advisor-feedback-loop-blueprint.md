# Sprint 16 — Advisor Feedback Loop (maduración con datos reales)

> Estado: blueprint (propuesta). No empezar TDD hasta aprobación.
> Predecesor obligatorio: Sprint 15 cerrado (commits `fa65891` + `33d59fc`).
> Sucesor sugerido: S17 (VirtualFS) — solo abrir tras cerrar S16.

---

## 0. Contexto

S15 dejó al Advisor funcionando "a ciegas": emite cuatro tipos de cards
(`forgotten_tool`, `phase_drift`, `recommend_skill_handoff`,
`grader_overdue`) con throttle (8 calls mínimo) y circuit breaker (≥3
calls/min lo apaga). Las constantes están **calibradas a ojo**, no contra
datos. Sin un canal de retorno, no hay forma de saber:

1. Qué cards son falsos positivos (y por qué).
2. Si el throttle es demasiado conservador (cards que llegan tarde) o
   demasiado agresivo (cards que llegan en cluster molesto).
3. Si una categoría está dominando el bundle a costa de las otras tres.

El sprint objetiva añadir un **feedback loop mínimo**: el usuario
califica cards con tres niveles, las constantes se afinan automáticamente
cuando hay suficiente señal, y Vicente puede ver un dashboard de salud
del Advisor con `apex_advisor_health()`.

NO entra en S16: rating implícito (deducir utilidad por behavior post-
card), promoción de trazas (dreaming), auto-export a HF, expansión de
categorías Hermes (5-15). Todos esos siguen como deuda futura del
roadmap.

---

## 1. Schema (1 tabla nueva)

```sql
CREATE TABLE advice_ratings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  advice_id   INTEGER NOT NULL,
  rating      TEXT    NOT NULL CHECK (rating IN
                ('useful', 'not_useful', 'false_positive')),
  reason      TEXT,                       -- razón libre del usuario
  rated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  rater       TEXT    NOT NULL DEFAULT 'user'
                CHECK (rater IN ('user', 'auto')),
  FOREIGN KEY (advice_id) REFERENCES advisor_advice(id)
                ON DELETE CASCADE
);
CREATE INDEX idx_advice_ratings_advice ON advice_ratings(advice_id);
CREATE INDEX idx_advice_ratings_rated  ON advice_ratings(rated_at);
```

Auto-migración vía `_ensure_db_schema` en `lib/context_db.py` (mismo
patrón que S15.A).

```sql
CREATE TABLE advisor_tuning_history (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  applied_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  category      TEXT    NOT NULL,        -- forgotten_tool | phase_drift | ...
  constant_name TEXT    NOT NULL,        -- e.g. 'min_calls_between_reviews'
  old_value     REAL    NOT NULL,
  new_value     REAL    NOT NULL,
  trigger_n_ratings  INTEGER NOT NULL,   -- N ratings que activaron el tune
  fp_rate_before     REAL,
  reason        TEXT
);
```

**Distinción clave de S15**: las constantes del Advisor (`MIN_CALLS_BETWEEN_REVIEWS`,
`CIRCUIT_BREAKER_CALLS_PER_MIN`, etc.) viven hoy como literales en
`lib/advisor.py`. S16 las migra a un dict mutable persistido en
`project_meta` (`advisor_constants`) que se lee en cada `build_bundle()`.
Si la fila no existe, fallback a los defaults actuales (sin rotura).

---

## 2. Tools MCP nuevas (3 → total 52)

```python
def apex_rate_advice(
    advice_id: int,
    rating: str,                # useful | not_useful | false_positive
    reason: str = "",
) -> dict:
    """INSERT advice_ratings. Si el advice_id no existe, ValueError.
    Si ya hay un rating del mismo rater, UPDATE (no duplica).
    Returns: {'rating_id': N, 'auto_tuning_triggered': bool}"""
```

```python
def apex_advisor_health(
    window_days: int = 30,
) -> dict:
    """Dashboard JSON-friendly:
      - total_advice_emitted (por categoría)
      - total_ratings (por rating × categoría)
      - false_positive_rate por categoría (None si <5 ratings)
      - constants_actuales (con defaults vs tuned)
      - tuning_history últimos 5
      - circuit_breaker_trips últimas 24h
    """
```

```python
def apex_advisor_apply_tuning(
    dry_run: bool = True,
) -> dict:
    """Ejecuta heurística de auto-tuning. dry_run=True devuelve
    propuestas sin aplicar; dry_run=False hace UPDATE y registra
    en advisor_tuning_history.
    Returns: {'proposals': [{category, constant, old, new, reason}]}"""
```

---

## 3. Heurística de auto-tuning

Mínimo 20 ratings por categoría antes de tunear. Tres reglas
deterministas:

| Categoría | Trigger | Acción |
|-----------|---------|--------|
| `forgotten_tool`         | FP rate >40%   | `min_calls_between_reviews`: 8 → 12 (+50%) |
| `phase_drift`            | FP rate >40%   | `phase_drift_window_min`: 30 → 45 (+50%) |
| `recommend_skill_handoff`| FP rate >40%   | `complexity_score_threshold`: 0.6 → 0.75 |
| `grader_overdue`         | FP rate >40%   | `grader_overdue_phases`: 2 → 3 |

Si `not_useful` rate >60% (sin ser FP) sobre la misma categoría:
**baja** la sensibilidad solo un escalón, no dos. La idea es que
`useful=relevante`, `not_useful=relevante pero ruidoso`, `false_positive=
no debería haber salido nunca`.

Anti-loop: una constante no se ajusta dos veces en <7 días salvo
override explícito vía `force=True` en `apex_advisor_apply_tuning`.

---

## 4. Hooks (1 nuevo)

`.claude/hooks/advisor-rating-watch.py` (UserPromptSubmit, no bloqueante).

Trigger semántico: si el último mensaje del usuario contiene una de las
frases registradas en `lib/feedback_phrases.py` (lista cerrada estilo
`wrapup_phrases`: "ese aviso fue útil", "esa card no servía", "falso
positivo de Advisor", etc.), busca el último advice mostrado y propone
rating con `apex_rate_advice` inyectando un bloque a stdout.

Si las constantes se han movido y nunca se han mostrado al usuario,
inyecta un aviso `[advisor-tuning] forgotten_tool: throttle 8→12 hace 3
días (FP 47%)` para mantener trazabilidad.

---

## 5. Skill (opcional, NO requisito de S16)

`skills/advisor-feedback/SKILL.md` describiendo cuándo ratear, qué
distinguir entre `not_useful` vs `false_positive`, y cómo leer el
output de `apex_advisor_health`. Texto breve (~80 líneas), sin tools
nuevas. Puede deferirse a S16.B si el sprint se infla.

---

## 6. Tasks descompuestas (TDD obligatorio)

| ID    | Subtarea                                         | LoC | Tests |
|-------|--------------------------------------------------|-----|-------|
| S16.1 | Schema + migración (`advice_ratings`, `advisor_tuning_history`) | 60  | 6     |
| S16.2 | `apex_rate_advice` + lib `lib/advisor_feedback.py`              | 120 | 10    |
| S16.3 | `apex_advisor_health` (queries agregadas)                       | 90  | 8     |
| S16.4 | Heurística `lib/advisor_tuning.py` + `apex_advisor_apply_tuning`| 130 | 12    |
| S16.5 | Migración constantes `advisor.py` → `project_meta` (con default fallback) | 60 | 6 |
| S16.6 | Hook `advisor-rating-watch.py` + `feedback_phrases.py`          | 100 | 8     |
| S16.7 | (Opcional) `skills/advisor-feedback/SKILL.md`                   | 80  | 0     |
|       | **Total**                                                       | ~640| ~50   |

Suite objetivo: 484 → ~534 verde. Sin S16.7: ~534 también, los tests no
van por skill.

### Orden recomendado

S16.1 → S16.2 → S16.5 (preparar terreno para tuning) → S16.4 → S16.3 →
S16.6 → S16.7. **S16.5 es crítico**: sin migrar las constantes a
`project_meta`, el tuning no tiene dónde escribir.

---

## 7. Tradeoffs explícitos

| Decisión | Alternativa | Razón |
|----------|-------------|-------|
| 3 niveles de rating | Estrellas 1-5 | Más caro de ratear → menos ratings → menos señal. 3 niveles es lo mínimo viable. |
| Auto-tuning en `apply_tuning` (manual) | Auto en cada rating | Vicente quiere ver propuestas antes de aplicar. Loop tight de "rate → constante muta → siguiente card cambia" es difícil de auditar. |
| 20 ratings/categoría mínimo | 10 | A 10 hay demasiado ruido (un usuario dudoso ya mueve 10%); 20 es el mínimo donde la mediana de FP rate es estable. |
| Hooks con trigger semántico | Hook que pregunta tras cada card | Demasiado intrusivo; si el usuario no quiere ratear, no fuerces. |
| `advisor_constants` en `project_meta` | Fichero `.apex/advisor.toml` | Una sola fuente de verdad (la BD). El TOML lo re-añadimos si el usuario lo pide. |

---

## 8. Riesgos a mitigar

1. **Bias de respuesta**. El usuario tiende a ratear cuando algo va mal.
   Pos-mortem: medir ratio `useful` reportado vs `useful` esperado por
   distribución de cards mostradas; si <30% del total recibe rating, las
   conclusiones son débiles.
2. **Falsos `false_positive`**. Una card puede ser técnicamente correcta
   pero contextualmente irrelevante (no es FP, es `not_useful`). Reason
   text obligatorio para `false_positive` (validación en
   `apex_rate_advice`).
3. **Tuning oscilatorio**. Si throttle sube y luego baja en pocos días,
   el Advisor se vuelve impredecible. El cooldown 7-días lo evita; si
   se viola con `force=True`, queda en `tuning_history`.

---

## 9. Tests previstos (~50)

- `test_advice_ratings_schema.py` (6): tabla creada, FK cascade, check
  constraints sobre `rating` y `rater`, índices, idempotencia
  re-migración.
- `test_advisor_feedback.py` (10): rate insert, update existing, FK
  inválida raises, reason obligatorio para FP, ratings cuentan por
  categoría, query agregadas.
- `test_advisor_health.py` (8): dashboard con BD vacía, BD con datos
  sintéticos, ventana 30d filtra, FP rate `None` si <5 ratings,
  constants_actuales muestra defaults si nunca tuneado.
- `test_advisor_tuning.py` (12): no tunea con <20 ratings, sí tunea con
  20+ y FP>40%, cooldown 7 días bloquea, force lo salta, dry_run no
  escribe, history registra cada tune.
- `test_advisor_constants_migration.py` (6): default fallback si
  `project_meta.advisor_constants` no existe, lectura desde BD
  override, escritura idempotente.
- `test_feedback_phrases.py` (8): lista cerrada normalizada (NFD),
  matching ES con tildes/mayúsculas, no fire en mensaje vacío, fire
  cuando frase está en mensaje largo.

---

## 10. Cómo arrancar S16.1

```
# Sesión nueva, primer prompt:
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -q   # confirmar 484 verde
# Crear test_advice_ratings_schema.py (red phase, 6 tests fallando)
# Aplicar migración en context_db.py
# Verde: 484 → 490
```

---

## 11. Notas finales

- Este sprint **no** rompe Advisor existente: si la tabla nueva no
  existe (BD vieja sin migrar), `build_bundle` sigue leyendo defaults
  hardcodeados. Migración progresiva.
- La tool `apex_advisor_health` también sirve como **señal pública** del
  estado del Advisor: cualquier usuario de APEX puede verla, no solo
  Vicente. Esto cumple la regla "un advisor que no se puede auditar es
  un advisor que no merece confianza".
- Si tras S16 el FP rate global sigue >25%, S17 se pospone y abrimos
  S16.B (categorías Hermes 5-11) antes de tocar VirtualFS. Es el único
  caso donde el orden estricto del roadmap se reordena.
