# Fase 3 — SPEC

Especificacion por fases, no monolitica. Empieza con reflexion profunda.

## Sub-pasos en orden

- **[3a]** Reflexion del problema: "Que problema REAL se esta resolviendo? Cual
  es el problema latente? Que valor aporta esta solucion que no existe hoy?"
  Escribir 2-3 parrafos de analisis. Guardar en wiki:
  `apex_wiki_add(slug="concepts/problem-analysis")`.
- **[3b]** Modelo de datos: Diagrama ER con Mermaid (erDiagram). Definir todas
  las entidades, sus atributos, y las relaciones entre ellas. Incluir tipos de
  datos, constraints, e indices. Registrar en wiki:
  `apex_wiki_add(slug="entities/data-model")`.
- **[3c]** Generar SPEC.md con secciones: Problema, Solucion, Usuarios,
  Funcionalidad core (fase 1), Funcionalidad extendida (fase 2+), Stack,
  Arquitectura, Restricciones, Metricas de exito.
- **[3c-bis]** **Referenciar tokens reales del DESIGN.md** (Sprint 10.1)
  cuando SPEC mencione UI: en lugar de "color primario azul" escribir
  "color primario = `accent` token de DESIGN.md". Eso evita drift entre
  SPEC y diseño implementado, y lo verificamos con
  `apex_design_md_validate()` antes de cerrar fase 3.
- **[3d]** Dividir la funcionalidad en checkpoints (MVP → v1 → v2). Cada
  checkpoint debe ser deployable y usable.
- **[3e]** Definir criterios de "hecho" para cada checkpoint.
- **[3f]** Revisar con el usuario. Pedir feedback en bloque (NO interrumpir con
  preguntas una a una).
- **[3g]** Registrar SPEC como wiki: `apex_wiki_add(title="SPEC", ...)`.
- **[3h]** `apex_set_phase(phase_number=3, status="completed")`.

## Criterio de salida

- SPEC.md completo con 9 secciones.
- Diagrama ER en wiki `entities/data-model`.
- Al menos 3 checkpoints deployables (MVP, v1, v2).
- Cada checkpoint con criterio de "hecho" escrito.
- Revision del usuario registrada.
- Fase marcada como `completed` en context.db.
