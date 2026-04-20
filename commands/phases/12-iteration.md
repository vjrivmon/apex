# Fase 12 — Iteracion

Para features, bugs y mejoras post-deploy.

## Sub-pasos en orden

- **[12a]** Leer context.db para entender estado actual:
  `apex_get_context(level="timeline")` + `apex_search_cross_project(query="...")`.
- **[12b]** Si es **feature nueva**: Mini-socratico (2 rondas: "Que
  resuelve?" + "Como afecta a lo existente?"). Escribir mini-SPEC (1
  parrafo: que, por que, criterio de hecho). Implementar → test → registrar
  con `apex_add_component`.
- **[12c]** Si es **bug**: Diagnosticar (reproducir, localizar, causa raiz).
  Fix minimo (cambiar lo menos posible). Test que cubra el bug (rojo sin
  fix, verde con fix). Registrar con
  `apex_add_error(error="...", solution="...", lesson="...")`.
- **[12d]** Si es **mejora/refactor**: Medir ANTES (tiempo, memoria, lineas,
  complejidad). Optimizar. Medir DESPUES y comparar. Solo mergear si la
  mejora es medible.
- **[12e]** SIEMPRE registrar en context.db con las herramientas MCP
  correspondientes.
- **[12f]** `apex_set_phase(phase_number=12, status="in_progress")` (esta
  fase nunca se "completa" definitivamente).

## Regla

Fase 12 es siempre `in_progress`. Es la fase viva del proyecto. Cada
iteracion genera nuevas decisiones y errores que alimentan la memoria
cross-project.
