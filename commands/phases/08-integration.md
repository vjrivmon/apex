# Fase 8 — Integracion

Conectar todo y verificar que funciona end-to-end. **Si el producto tiene
UI web, Playwright real es obligatorio — Streamlit NO cuenta como
validación de UI web** (lección focusnow#3).

## Gate de entrada (OBLIGATORIO antes del sub-paso [8a])

```
apex_phase_entry_check(phase=8, context_hint="<tipo de producto: web/CLI/bot>")
```

Lee el bloque `### Lecciones cross-project aplicadas`. Presta especial atencion
a errores de datos mock hardcodeados (leccion focusnow#3) y schema contracts
no aplicados entre capas (patron tfg-tutor#5).

**Queries internas**: "integration end-to-end errores", "mock datos hardcoded frontend".

## Sub-pasos en orden

- **[8a]** Conectar adaptadores al lifespan de la app (dependency injection).
- **[8b]** Endpoints / CLI commands / bot handlers funcionales con
  **schema contracts** (Pydantic en Python, Zod/io-ts en TypeScript)
  entre capas — previene tfg-tutor#5 (datos no propagados entre
  componentes).
- **[8c]** **Si producto = web**: Playwright spec mínimo del flujo
  crítico (login, acción principal, persistencia). Streamlit sólo se
  acepta como validación intermedia para CLI/bot, NO para UI web.
  **Si producto = CLI/bot/MCP**: smoke test en terminal del flujo
  crítico es suficiente.
- **[8d]** Verificar flujo completo: input → proceso → output → persistencia.
  Capturar screenshot del E2E si es web (`mcp__playwright__browser_take_screenshot`).
- **[8e]** Si algo falla: registrar con `apex_add_error` y corregir antes de
  avanzar.
- **[8e-sec]** Verificar headers de seguridad en la capa de aplicacion:
  - CORS: lista blanca explicita, nunca `*` en produccion.
  - Si hay endpoints que reciben archivos: validar tipo MIME y tamaño maximo.
  - Si hay endpoints que reciben JSON: schema validation (Pydantic/Zod) en TODAS las rutas publicas.
  Registrar gaps con `apex_add_error(phase=8, severity="high", ...)` si se detectan.
- **[8f]** Conventional commit del integration milestone.
- **[8g]** Ejecutar `apex_grader_evaluate(phase=8, mode="full",
  component_types=[...])`. Para `component_types=["web"]`, el grader
  exige `e2e_for_web_ui=true` (Playwright detectado).
- **[8h]** Si verdict pasa: `apex_set_phase(phase_number=8,
  status="completed")`.

## Skills recomendadas

- **`tdd`** (Sprint 14) — los tests de integracion cross-modulo son la
  superficie natural del bucle red-green-refactor a este nivel. Aplica
  la regla de mocking: solo en bordes del sistema (APIs externas, DB,
  tiempo, fs), nunca colaboradores internos. Si descubres que un modulo
  necesita ser mockeado para testarlo, es señal de un seam mal puesto.

## Criterio de salida (outcome-based)

- DI lifecycle configurado y schema contracts en frontera de capa.
- **Si UI web**: Playwright config + 1 spec verde del flujo crítico.
- **Si CLI/bot**: smoke test del flujo crítico en terminal.
- Backend devuelve datos reales (no mock, no hardcoded).
- Verdict del grader: `should_block=false`, sin issue `mock_data`.
- Fase marcada como `completed` (sólo si verdict pasa).
