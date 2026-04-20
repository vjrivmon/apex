# SecondBrain — Orquestador del segundo cerebro

## Qué es esto

El "segundo cerebro" de APEX combina 4 piezas que trabajan juntas:

1. **`lib/ingest.py`** — QUERY→INGEST pipeline. Lee `.apex/raw/` y genera
   páginas wiki estructuradas.
2. **`lib/lint.py`** — Self-heal. Detecta contradicciones, huérfanos,
   stale, bloqueos.
3. **`lib/synthesis.py`** — Density-triggered. Cuando hay suficiente
   material fresco, ejecuta `dream_deep()` y promueve señales a
   `wiki/synthesis/`.
4. **`db.search_hybrid()`** — Retrieval 70/30 FTS+keyword. Mejora
   recall en queries con inflexiones, typos o términos compuestos.

Este skill no ejecuta código — orquesta las 3 herramientas anteriores
según el contexto.

## Cuándo activar

| Situación | Acción |
|-----------|--------|
| Usuario mete archivos nuevos en `.apex/raw/` | `apex_ingest_source(path, auto_wiki=True)` sobre cada archivo |
| Al iniciar la semana / fase nueva | `apex_lint_second_brain()` → revisar findings críticos |
| Al cerrar fase mayor (3, 9, 14) | `apex_synthesize(trigger="auto")` |
| Usuario pide "¿dónde lo vimos?" / "¿hemos decidido X?" | `apex_search_cross_project` + `apex_search` con mode=hybrid |
| Semanalmente (automático) | Hook `weekly-design-lint.py` ya lo hace para inspiración visual |

## Flujo completo (cuando hay mucho material nuevo)

1. **Ingest** — `apex_ingest_source` sobre cada archivo nuevo de
   `.apex/raw/`. Las páginas wiki se generan con frontmatter, wikilinks
   y bias flags.
2. **Retrieval** — `apex_search_hybrid` cuando el agente o usuario
   necesite contexto. Si no encuentra, fallback a
   `apex_search_cross_project` (hub.db).
3. **Lint** — `apex_lint_second_brain` antes de avanzar de fase.
   Bloquear si hay `critical`. Aplicar auto-fixes de NS-001.
4. **Synthesis** — `apex_synthesize` cuando `lint` confirma salud y la
   densidad supera umbrales. El output queda en `wiki/synthesis/YYYY-MM-DD.md`.

## Reglas

- **Idempotencia**: los 3 módulos se pueden ejecutar N veces sin efecto
  secundario. Ingest sobre el mismo archivo re-escribe la página wiki;
  lint solo lee (excepto `--apply`); synthesis respeta el cutoff por
  fecha (un informe por día).

- **Nunca corromper `.apex/raw/`**. Es fuente inmutable. Los cambios se
  reflejan en `wiki/`, no al revés.

- **Cross-link > aislamiento**. Cada página wiki creada debe tener al
  menos un wikilink hacia otra. Si no, el lint marcará WK-002.

- **No exagerar en bias flags**. Las heurísticas son orientativas
  (`always`, `never`, superlativos). El agente puede ignorarlas si el
  contexto lo justifica — pero debe registrarlo como decisión.

## Regla cross-project (OBLIGATORIA)

Antes de crear una página wiki desde scratch, consultar:

```
apex_search_cross_project(query="<tema>")
```

para reusar conceptos ya establecidos en otros proyectos. Si existen,
citar y enlazar — no duplicar.
