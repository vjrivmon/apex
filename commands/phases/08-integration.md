# Fase 8 — Integracion

Conectar todo y verificar que funciona end-to-end. **Si el producto tiene
UI web, Playwright real es obligatorio — Streamlit NO cuenta como
validación de UI web** (lección focusnow#3).

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
- **[8f]** Conventional commit del integration milestone.
- **[8g]** Ejecutar `apex_grader_evaluate(phase=8, mode="full",
  component_types=[...])`. Para `component_types=["web"]`, el grader
  exige `e2e_for_web_ui=true` (Playwright detectado).
- **[8h]** Si verdict pasa: `apex_set_phase(phase_number=8,
  status="completed")`.

## Criterio de salida (outcome-based)

- DI lifecycle configurado y schema contracts en frontera de capa.
- **Si UI web**: Playwright config + 1 spec verde del flujo crítico.
- **Si CLI/bot**: smoke test del flujo crítico en terminal.
- Backend devuelve datos reales (no mock, no hardcoded).
- Verdict del grader: `should_block=false`, sin issue `mock_data`.
- Fase marcada como `completed` (sólo si verdict pasa).
