# Fase 4 — Edge cases

ANTES de escribir codigo, pensar en que puede fallar.

## Sub-pasos en orden

- **[4a]** Generar TODOS los edge cases posibles, sin limite. Agrupar por
  categoria: inputs invalidos, red/servicios caidos, concurrencia, datos
  corruptos, limites (0, max, unicode, inyeccion), permisos, estados
  imposibles, recursos agotados (disco, memoria, conexiones), temporales
  (timezone, DST, leap year), internacionalizacion,
  navegadores/dispositivos. Cuantos mas, mejor. NO limitar.
- **[4b]** Para cada edge case: describir escenario, comportamiento esperado,
  y estrategia de mitigacion.
- **[4c]** Priorizar: cuales bloquean el MVP y cuales son post-MVP.
- **[4d]** Registrar con `apex_wiki_add(title="EDGE-CASES", ...)`.
- **[4e]** `apex_set_phase(phase_number=4, status="completed")`.

## Criterio de salida

- Al menos 30 edge cases documentados (listado "cuantos mas, mejor").
- Cada uno con escenario + comportamiento esperado + mitigacion.
- Priorizacion MVP vs post-MVP explicita.
- Wiki `EDGE-CASES` creado.
- Fase marcada como `completed` en context.db.
