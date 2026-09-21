# Fase 7 — Infraestructura

Implementar los adaptadores que conectan con el mundo exterior.

## Gate de entrada (OBLIGATORIO antes del sub-paso [7a])

```
apex_phase_entry_check(phase=7, context_hint="<BD + servicios externos del proyecto>")
```

Lee el bloque `### Lecciones cross-project aplicadas`. Presta especial atencion
a errores de migraciones, queries sin parametrizar, o adapters que no implementan
su puerto correctamente.

**Queries internas**: "database adapter migraciones errores", "LLM adapter infraestructura".

## Sub-pasos en orden

- **[7a]** Base de datos: adapter, migraciones, seed data.
- **[7b]** Servicios externos: LLM adapter, APIs de terceros, scraping.
- **[7c]** Verificar que cada adapter implementa su puerto/interfaz
  correctamente.
- **[7d]** Test manual rapido: conectar, insertar, leer, borrar.
- **[7d-sec]** Verificar que todas las queries a BD usan parametros (?, $1, :param),
  NUNCA interpolacion de strings. Ejecutar:
  `grep -rn "f".*SELECT\|f".*INSERT\|f".*UPDATE\|f".*DELETE\|%.*SELECT\|%.*INSERT" . --include="*.py" --include="*.ts"`.
  Si hay hits: son SQL injection candidates — corregir antes de continuar.
  Verificar que credenciales de BD vienen de variables de entorno, no hardcodeadas.
- **[7e]** Registrar con `apex_add_component`.
- **[7f]** `apex_grader_evaluate(phase=7, mode="deterministic")`.
  Si `should_block=true`, atacar los issues y reevaluar: el gate
  rechaza la transicion mientras el verdict siga bloqueando.
- **[7g]** `apex_set_phase(phase_number=7, status="completed")`.

## Criterio de salida

- Adapters creados para cada port definido en fase 6.
- Migraciones BD ejecutables.
- Test manual CRUD verificado.
- Fase marcada como `completed` en context.db.
