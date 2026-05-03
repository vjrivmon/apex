---
name: grill-with-docs
description: Sesión de interrogatorio que confronta tu plan contra el modelo de dominio existente, afila la terminología y actualiza la documentación (CONTEXT.md, ADRs / wiki/decisions/) inline conforme las decisiones cristalizan. Usar cuando el usuario quiere estresar un plan contra el lenguaje del proyecto y las decisiones documentadas. Triggers ES/EN — grill, parrilla, interrogar, "afina mi plan", stress-test plan, challenge plan.
---

<what-to-do>

Interroga al usuario sin tregua sobre cada aspecto del plan hasta alcanzar un entendimiento compartido. Recorre cada rama del árbol de diseño resolviendo dependencias entre decisiones una por una. Para cada pregunta, ofrece tu respuesta recomendada.

Haz las preguntas de una en una, esperando feedback antes de continuar.

Si una pregunta puede resolverse explorando el código, explora el código en lugar de preguntar.

</what-to-do>

<supporting-info>

## Conciencia del dominio

Durante la exploración del código, busca también la documentación existente.

### Estructura de archivos

La mayoría de repos tienen un único contexto:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/                ← convención Matt Pocock
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
├── wiki/
│   └── decisions/          ← convención APEX (preferida si existe)
│       ├── 2026-05-03-api-stack.md
│       └── 2026-05-04-test-strategy.md
└── src/
```

**Puente APEX**: si el proyecto tiene `wiki/decisions/` (output del scaffold APEX), usa esa carpeta para las decisiones en lugar de `docs/adr/`. Si no existe, créala perezosamente cuando aparezca la primera decisión que merezca ser registrada.

Si existe `CONTEXT-MAP.md` en la raíz, el repo tiene múltiples contextos. El mapa apunta a dónde vive cada uno:

```
/
├── CONTEXT-MAP.md
├── docs/
│   └── adr/                          ← decisiones de sistema
├── src/
│   ├── ordering/
│   │   ├── CONTEXT.md
│   │   └── docs/adr/                 ← decisiones por contexto
│   └── billing/
│       ├── CONTEXT.md
│       └── docs/adr/
```

Crea archivos perezosamente — sólo cuando tengas algo que escribir. Si no existe `CONTEXT.md`, créalo cuando se resuelva el primer término. Si no existen `wiki/decisions/` ni `docs/adr/`, crea uno cuando haga falta el primer ADR.

## Durante la sesión

### Confrontar contra el glosario

Cuando el usuario use un término que entre en conflicto con el lenguaje existente en `CONTEXT.md`, señálalo de inmediato. "Tu glosario define 'cancelación' como X, pero parece que te refieres a Y — ¿cuál es?"

### Afilar lenguaje difuso

Cuando el usuario use términos vagos o sobrecargados, propón un término canónico preciso. "Estás diciendo 'cuenta' — ¿te refieres al Customer o al User? Son cosas distintas."

### Discutir escenarios concretos

Cuando se discutan relaciones del dominio, estresa la conversación con escenarios específicos. Inventa escenarios que prueben los casos límite y obliguen al usuario a ser preciso sobre los bordes entre conceptos.

### Cruzar referencias con el código

Cuando el usuario afirme cómo funciona algo, comprueba que el código lo respalda. Si encuentras una contradicción, sácala a la superficie: "Tu código cancela Orders enteras, pero acabas de decir que la cancelación parcial es posible — ¿cuál es la verdadera?"

### Actualizar CONTEXT.md inline

Cuando se resuelva un término, actualiza `CONTEXT.md` ahí mismo. No los acumules — captúralos según ocurran. Usa el formato en [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

No acoples `CONTEXT.md` a detalles de implementación. Sólo incluye términos que tengan sentido para un experto del dominio.

### Ofrecer ADRs con moderación

Sólo ofrece crear un ADR cuando los tres son ciertos:

1. **Difícil de revertir** — el coste de cambiar de opinión más tarde es significativo
2. **Sorprendente sin contexto** — un futuro lector se preguntará "¿por qué lo hicieron así?"
3. **Resultado de un trade-off real** — había alternativas genuinas y se eligió una por motivos específicos

Si falta cualquiera de los tres, salta el ADR. Usa el formato en [ADR-FORMAT.md](./ADR-FORMAT.md).

**Puente APEX**: si el proyecto tiene `wiki/decisions/` (estándar APEX), escribe la decisión ahí con el formato `YYYY-MM-DD-slug.md`. Si no, usa `docs/adr/0001-slug.md` con numeración secuencial.

</supporting-info>
