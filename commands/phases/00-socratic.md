# Fase 0 — Socratico

Cuestiona la idea ANTES de construir nada. Investiga el mercado. Filtra ideas
sin valor real.

## Sub-pasos en orden

- **[0a]** Recopilar contexto: Escuchar la idea completa del usuario sin
  interrumpir. Extraer: problema, publico objetivo, tipo de solucion propuesta,
  dominio.
- **[0b]** Investigacion de mercado: Usar WebSearch para buscar si ya existen
  soluciones similares. Buscar: "{idea} app", "{problema} herramienta",
  "{dominio} software open source". Analizar resultados:
  - Si existen competidores: presentar al usuario con analisis de
    fortalezas/debilidades. Preguntar: "Que haria tu version diferente?"
  - Si no existen: posible Oceano Azul. Preguntar: "Por que crees que nadie lo
    ha hecho? Falta de demanda o falta de ejecucion?"
- **[0c]** Ronda 1: "Que problema REAL estas resolviendo? Como lo resuelves HOY
  sin esta herramienta?"
- **[0d]** Ronda 2: "Realmente necesitas UI? Un CLI, bot de Telegram, servidor
  MCP, o script no basta?"
- **[0e]** Ronda 3: "Quien lo usa? Con que frecuencia? Necesita funcionar
  offline?"
- **[0f]** Ronda 4: "Cual es el escenario donde falla? Que pasa si la BD se
  corrompe, si el servicio externo cae, si no hay internet?"
- **[0g]** Reflexion de valor: Escribir un parrafo que explique el problema
  latente que existe y que aporta de valor la solucion propuesta. Guardar en
  wiki: `apex_wiki_add(slug="concepts/value-proposition")`.
- **[0h]** Registrar TODAS las decisiones + investigacion de mercado con
  `apex_add_decision(phase=0, ...)`. Incluir resultados de la busqueda de
  competidores.
- **[0i]** Cross-project retrieval obligatorio: antes de cerrar esta fase,
  ejecutar `apex_search_cross_project(query="<idea>")` para aprender de
  proyectos previos con el mismo dominio o stack.
- **[0j]** `apex_set_phase(phase_number=0, status="completed")`

## Skills recomendadas

- **`grill-with-docs`** (Sprint 14) — tras las rondas socraticas, si la
  idea sobrevive, invoca esta skill para estresar el plan contra el
  lenguaje del dominio. Crea/actualiza vocabulario canonico
  (CONTEXT.md o `wiki/entities/concepts/`) y registra decisiones cargadas
  en `wiki/decisions/` con formato `YYYY-MM-DD-slug.md`. Refuerza la
  fase, no la reemplaza.

## Criterio de salida

- 4 rondas socraticas registradas.
- Parrafo de value proposition guardado en wiki.
- Al menos 1 busqueda de competidores con conclusion.
- Cross-project retrieval ejecutado.
- Fase marcada como `completed` en context.db.
