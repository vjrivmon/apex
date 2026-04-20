# Fase 8 — Integracion

Conectar todo y verificar que funciona end-to-end.

## Sub-pasos en orden

- **[8a]** Conectar adaptadores al lifespan de la app (dependency injection).
- **[8b]** Endpoints / CLI commands / bot handlers funcionales.
- **[8c]** Si tiene UI: Streamlit para validar datos reales ANTES de frontend
  definitivo.
- **[8d]** Verificar flujo completo: input → proceso → output → persistencia.
- **[8e]** Si algo falla: registrar con `apex_add_error` y corregir antes de
  avanzar.
- **[8f]** `apex_set_phase(phase_number=8, status="completed")`.

## Criterio de salida

- DI lifecycle configurado.
- Al menos 1 flujo end-to-end probado en terminal/Streamlit.
- Backend devuelve datos reales.
- Fase marcada como `completed` en context.db.
