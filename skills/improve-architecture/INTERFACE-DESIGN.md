# Diseño de Interface

Cuando el usuario quiera explorar interfaces alternativas para un candidato de profundización elegido, usa este patrón de sub-agentes paralelos. Basado en "Design It Twice" (Ousterhout) — tu primera idea es improbable que sea la mejor.

Usa el vocabulario de [LANGUAGE.md](LANGUAGE.md) — **module**, **interface**, **seam**, **adapter**, **leverage**.

## Proceso

### 1. Enmarca el espacio del problema

Antes de spawnear sub-agentes, escribe una explicación user-facing del espacio del problema para el candidato elegido:

- Las restricciones que cualquier nueva interface tendría que satisfacer
- Las dependencias en las que se apoyaría, y a qué categoría pertenecen (ver [DEEPENING.md](DEEPENING.md))
- Un sketch de código ilustrativo aproximado para anclar las restricciones — no una propuesta, sólo una forma de hacer concretas las restricciones

Muestra esto al usuario, y procede inmediatamente al Paso 2. El usuario lee y piensa mientras los sub-agentes trabajan en paralelo.

### 2. Spawn sub-agentes

Spawnea 3+ sub-agentes en paralelo usando la tool Agent. Cada uno debe producir una interface **radicalmente distinta** para el módulo profundizado.

Promptea cada sub-agent con un brief técnico separado (file paths, detalles de coupling, categoría de dependencia de [DEEPENING.md](DEEPENING.md), qué se sienta detrás del seam). El brief es independiente de la explicación user-facing del espacio del problema del Paso 1. Da a cada agente una restricción de diseño distinta:

- Agente 1: "Minimiza la interface — apunta a 1-3 entry points máximo. Maximiza leverage por entry point."
- Agente 2: "Maximiza flexibilidad — soporta muchos casos de uso y extensión."
- Agente 3: "Optimiza para el caller más común — haz trivial el caso por defecto."
- Agente 4 (si aplica): "Diseña en torno a ports & adapters para dependencias cross-seam."

Incluye en el brief tanto vocabulario de [LANGUAGE.md](LANGUAGE.md) como de CONTEXT.md para que cada sub-agent nombre cosas consistentemente con el lenguaje de arquitectura y el de dominio del proyecto.

Cada sub-agent produce:

1. Interface (tipos, métodos, params — más invariantes, ordering, modos de error)
2. Ejemplo de uso mostrando cómo los callers la usan
3. Qué oculta la implementación detrás del seam
4. Estrategia de dependencias y adapters (ver [DEEPENING.md](DEEPENING.md))
5. Trade-offs — dónde el leverage es alto, dónde es delgado

### 3. Presentar y comparar

Presenta los diseños secuencialmente para que el usuario absorba cada uno, después compáralos en prosa. Contrasta por **depth** (leverage en la interface), **locality** (dónde se concentra el cambio) y posición del **seam**.

Tras comparar, da tu propia recomendación: qué diseño crees que es más fuerte y por qué. Si elementos de distintos diseños se combinarían bien, propón un híbrido. Sé opinionado — el usuario quiere una lectura fuerte, no un menú.
