# Fase 7 — Infraestructura

Implementar los adaptadores que conectan con el mundo exterior.

## Sub-pasos en orden

- **[7a]** Base de datos: adapter, migraciones, seed data.
- **[7b]** Servicios externos: LLM adapter, APIs de terceros, scraping.
- **[7c]** Verificar que cada adapter implementa su puerto/interfaz
  correctamente.
- **[7d]** Test manual rapido: conectar, insertar, leer, borrar.
- **[7e]** Registrar con `apex_add_component`.
- **[7f]** `apex_set_phase(phase_number=7, status="completed")`.

## Criterio de salida

- Adapters creados para cada port definido en fase 6.
- Migraciones BD ejecutables.
- Test manual CRUD verificado.
- Fase marcada como `completed` en context.db.
