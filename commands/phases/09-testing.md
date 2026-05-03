# Fase 9 — Testing

## Sub-pasos en orden

- **[9a]** Unit tests: cobertura minima 80% en dominio (entidades, casos de
  uso, agentes). Ejecutar y verificar que pasan.
- **[9b]** Integration tests: BD real, APIs reales, servicios conectados. NO
  mockear lo que luego va a produccion.
- **[9c]** E2E tests con Playwright siguiendo flujos reales de usuario. Cada
  flujo mapeado en fase 2 (ej: crear item → ver en lista → completar). Si
  falla: capturar screenshot + estado + error y registrar con
  `apex_add_error`.
- **[9d]** Edge case tests: implementar los escenarios de EDGE-CASES.md
  marcados como MVP-blocking.
- **[9e]** Verificar que TODOS los tests pasan antes de continuar.
- **[9f]** Coverage report: Ejecutar coverage y generar report HTML.
  - Python: `pytest --cov --cov-report=html`
  - JS/TS: `npx nyc` / `jest --coverage`
  Threshold minimo: 80% en domain, 60% global. Si no se alcanza, registrar
  que falta y como next_step con `apex_add_next_step`.
- **[9g]** `apex_set_phase(phase_number=9, status="completed")`.

## Skills recomendadas

- **`tdd`** (Sprint 14) — usa tests-as-specification. Cada test describe
  una capacidad ("user can checkout with valid cart"), no un detalle
  interno ("checkout calls paymentService.process"). Si un test rompe
  cuando refactorizas sin cambiar comportamiento, esta testando
  implementacion: borrarlo o reformularlo contra la interface publica.
- **`diagnose`** (Sprint 14) — comodin para cualquier bug que aparezca
  durante esta fase. Bucle de 6 fases: feedback loop → reproduce →
  hipotetiza (3-5 ranqueadas) → instrumenta (logs `[DEBUG-...]`
  etiquetados) → fix + test de regresion → cleanup. Cierra con
  `apex_add_error` para que A1 `override_clusters` del doctor lo recoja.

## Criterio de salida

- Unit + integration + E2E verde.
- Coverage domain >=80%, global >=60%.
- Edge cases MVP-blocking cubiertos.
- Fase marcada como `completed` en context.db.
