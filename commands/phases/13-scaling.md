# Fase 13 — Escalado

## Sub-pasos en orden

- **[13a]** Performance profiling: medir, NO adivinar. Identificar los 3
  cuellos de botella reales con datos (tiempo de respuesta, queries lentas,
  memoria).
- **[13b]** Caching strategy: definir que se cachea, TTLs, estrategia de
  invalidacion. Registrar con `apex_add_decision(category="performance")`.
- **[13c]** Monitoring setup: health checks, alertas, metricas. Integrar
  con templates de `apex_scaffold_devops` (Prometheus, Grafana, Loki).
- **[13d]** Health dashboard: generar un endpoint `/status` o panel
  Streamlit que muestre:
  - Backend UP/DOWN con timestamp del ultimo check
  - BD conexion OK/FAIL, tamano, ultimo backup
  - Servicios externos estado de cada uno
  - Ultima actividad timestamp + tipo
  - Disco espacio usado/libre
  - Errores recientes ultimos 10 de context.db
- **[13e]** `apex_grader_evaluate(phase=13, mode="deterministic")`.
  Si `should_block=true`, atacar los issues y reevaluar: el gate
  rechaza la transicion mientras el verdict siga bloqueando.
- **[13f]** `apex_set_phase(phase_number=13, status="completed")`.

## Skills recomendadas

- **`improve-architecture`** (Sprint 14) — escalar hace fricciones
  arquitectonicas inevitables (modulos shallow se vuelven cuellos de
  botella, seams mal puestos filtran across boundaries). Aplica el
  vocabulario canonico (depth, seam, adapter, leverage, locality) y la
  regla "un adapter = seam hipotetico, dos = seam real" para no
  introducir indireccion innecesaria. Para interfaces criticas, usa
  el patron Design It Twice con 3+ sub-agentes en paralelo.

## Criterio de salida

- Profile de los 3 cuellos principales documentado.
- Caching implementado donde haya mejora medible.
- Dashboards en Grafana con paneles basicos.
- `/status` endpoint con payload completo.
- Fase marcada como `completed` en context.db.
