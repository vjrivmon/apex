---
name: improve-architecture
description: Encuentra oportunidades de profundización (deepening) en un codebase, informado por el lenguaje del dominio en CONTEXT.md y las decisiones en wiki/decisions/ o docs/adr/. Usar cuando el usuario quiere mejorar arquitectura, encontrar oportunidades de refactor, consolidar módulos fuertemente acoplados, o hacer un codebase más testeable y AI-navegable. Triggers ES/EN — improve architecture, "mejorar arquitectura", deepening, refactor, "demasiados módulos pequeños", "es difícil de testear".
---

# Improve Codebase Architecture

Saca a la superficie fricción arquitectónica y propón **oportunidades de profundización (deepening)** — refactors que convierten módulos shallow en deep. El objetivo es testabilidad y navegabilidad por agentes IA.

## Glosario

Usa estos términos exactamente en cada sugerencia. Lenguaje consistente es el punto — no derives en "componente", "servicio", "API" o "boundary". Definiciones completas en [LANGUAGE.md](LANGUAGE.md).

- **Module** — cualquier cosa con interface e implementación (función, clase, paquete, slice).
- **Interface** — todo lo que un caller debe saber para usar el módulo: tipos, invariantes, modos de error, ordering, config. No sólo la firma de tipos.
- **Implementation** — el código dentro.
- **Depth** — leverage en la interface: mucho comportamiento detrás de una interface pequeña. **Deep** = leverage alto. **Shallow** = interface casi tan compleja como la implementación.
- **Seam** — donde vive una interface; un sitio donde alterar comportamiento sin editar in place. (Usa esto, no "boundary".)
- **Adapter** — algo concreto que satisface una interface en un seam.
- **Leverage** — lo que los callers ganan de la profundidad.
- **Locality** — lo que ganan los mantenedores: cambio, bugs, conocimiento concentrados en un sitio.

Principios clave (ver [LANGUAGE.md](LANGUAGE.md) para la lista completa):

- **Test de borrado**: imagina borrar el módulo. Si la complejidad desaparece, era un pass-through. Si reaparece a través de N callers, se ganaba el sustento.
- **La interface es la superficie de test.**
- **Un adapter = seam hipotético. Dos adapters = seam real.**

Esta skill está *informada* por el modelo de dominio del proyecto. El lenguaje de dominio da nombres a buenos seams; los ADRs registran decisiones que la skill no debería re-litigar.

**Puente APEX**: si existe `wiki/decisions/`, léelas como ADRs antes de proponer cualquier refactor. Si una propuesta contradice una decisión, márcalo explícitamente. Si el proyecto tiene `wiki/entities/concepts/`, usa ese vocabulario para nombrar módulos profundizados.

## Proceso

### 1. Explorar

Lee primero el glosario de dominio del proyecto y cualquier ADR en el área que tocas.

Después usa la tool Agent con `subagent_type=Explore` para recorrer el codebase. No sigas heurísticas rígidas — explora orgánicamente y anota dónde experimentas fricción:

- ¿Dónde entender un concepto requiere botar entre muchos módulos pequeños?
- ¿Dónde hay módulos **shallow** — interface casi tan compleja como la implementación?
- ¿Dónde se han extraído funciones puras sólo para testabilidad pero los bugs reales viven en cómo se llaman (sin **locality**)?
- ¿Dónde hay módulos fuertemente acoplados que filtran a través de sus seams?
- ¿Qué partes del codebase no están testadas, o son difíciles de testar a través de su interface actual?

Aplica el **test de borrado** a cualquier cosa que sospeches sea shallow: ¿borrarla concentraría la complejidad o sólo la movería? Un "sí, concentra" es la señal que quieres.

### 2. Presentar candidatos

Presenta una lista numerada de oportunidades de profundización. Para cada candidato:

- **Files** — qué archivos/módulos están involucrados
- **Problem** — por qué la arquitectura actual causa fricción
- **Solution** — descripción en lenguaje claro de qué cambiaría
- **Benefits** — explicado en términos de locality y leverage, y también cómo mejorarían los tests

**Usa el vocabulario de CONTEXT.md para el dominio, y el de [LANGUAGE.md](LANGUAGE.md) para la arquitectura.** Si `CONTEXT.md` define "Order", habla del "Order intake module" — no del "FooBarHandler", y no del "Order service".

**Conflictos con ADRs**: si un candidato contradice un ADR existente, sácalo a la superficie sólo cuando la fricción sea lo bastante real para justificar reabrir el ADR. Márcalo claramente (p.ej. _"contradice ADR-0007 — pero merece reabrirse porque…"_). No listes cada refactor teórico que un ADR prohíba.

NO propongas interfaces todavía. Pregunta al usuario: "¿Cuál de éstas quieres explorar?"

### 3. Bucle de grilling

Una vez que el usuario elija un candidato, entra en una conversación de grilling. Recorre el árbol de diseño con él — restricciones, dependencias, la forma del módulo profundizado, qué se sienta detrás del seam, qué tests sobreviven.

Los efectos secundarios ocurren inline conforme las decisiones cristalizan:

- **¿Nombrar un módulo profundizado con un concepto que no está en `CONTEXT.md`?** Añade el término a `CONTEXT.md` — misma disciplina que `/grill-with-docs` (ver [CONTEXT-FORMAT.md](../grill-with-docs/CONTEXT-FORMAT.md)). Crea el archivo perezosamente si no existe.
- **¿Afilar un término difuso durante la conversación?** Actualiza `CONTEXT.md` ahí mismo.
- **¿El usuario rechaza el candidato con una razón cargada?** Ofrece un ADR (en `wiki/decisions/` si existe la carpeta APEX, o en `docs/adr/`), enmarcado como: _"¿Quieres que registre esto como ADR para que futuras revisiones de arquitectura no lo vuelvan a sugerir?"_ Sólo ofrece cuando la razón realmente sería necesaria por un futuro explorador para evitar re-sugerir lo mismo — salta razones efímeras ("ahora no merece la pena") y obvias. Ver [ADR-FORMAT.md](../grill-with-docs/ADR-FORMAT.md).
- **¿Quieres explorar interfaces alternativas para el módulo profundizado?** Ver [INTERFACE-DESIGN.md](INTERFACE-DESIGN.md).
