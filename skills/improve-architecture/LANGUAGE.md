# Lenguaje

Vocabulario compartido para cada sugerencia de esta skill. Usa estos términos exactamente — no sustituyas con "componente", "servicio", "API" o "boundary". Lenguaje consistente es el punto entero.

## Términos

**Module**
Cualquier cosa con interface e implementación. Deliberadamente agnóstico de escala — aplica igual a una función, clase, paquete o slice que cruza tiers.
_Evitar_: unit, component, service.

**Interface**
Todo lo que un caller debe saber para usar el módulo correctamente. Incluye la firma de tipos, pero también invariantes, restricciones de ordering, modos de error, configuración requerida y características de rendimiento.
_Evitar_: API, signature (demasiado estrecho — esos refieren sólo a la superficie a nivel de tipos).

**Implementation**
Lo que está dentro de un módulo — su cuerpo de código. Distinto de **Adapter**: una cosa puede ser un adapter pequeño con una implementación grande (un Postgres repo) o un adapter grande con implementación pequeña (un fake en memoria). Tira de "adapter" cuando el seam es el tema; "implementation" en otros casos.

**Depth**
Leverage en la interface — la cantidad de comportamiento que un caller (o test) puede ejercitar por unidad de interface que tienen que aprender. Un módulo es **deep** cuando una gran cantidad de comportamiento se sienta detrás de una interface pequeña. Un módulo es **shallow** cuando la interface es casi tan compleja como la implementación.

**Seam** _(de Michael Feathers)_
Un sitio donde puedes alterar el comportamiento sin editar en ese sitio. La *ubicación* en la cual vive la interface de un módulo. Elegir dónde poner el seam es su propia decisión de diseño, distinta de qué va detrás.
_Evitar_: boundary (sobrecargado con bounded context de DDD).

**Adapter**
Una cosa concreta que satisface una interface en un seam. Describe *rol* (qué slot rellena), no sustancia (qué hay dentro).

**Leverage**
Lo que los callers ganan de la depth. Más capacidad por unidad de interface que tienen que aprender. Una implementación paga a través de N call sites y M tests.

**Locality**
Lo que ganan los mantenedores de la depth. Cambio, bugs, conocimiento y verificación se concentran en un sitio en lugar de propagarse a callers. Arregla una vez, arreglado en todos lados.

## Principios

- **Depth es propiedad de la interface, no de la implementación.** Un módulo deep puede internamente componerse de partes pequeñas, mockables, swappables — simplemente no son parte de la interface. Un módulo puede tener **internal seams** (privados a su implementación, usados por sus propios tests) además del **external seam** en su interface.
- **El test de borrado.** Imagina borrar el módulo. Si la complejidad desaparece, el módulo no escondía nada (era pass-through). Si la complejidad reaparece a través de N callers, el módulo se ganaba el sustento.
- **La interface es la superficie de test.** Callers y tests cruzan el mismo seam. Si quieres testar *más allá* de la interface, el módulo probablemente tiene la forma equivocada.
- **Un adapter significa seam hipotético. Dos adapters significa seam real.** No introduzcas un seam a menos que algo realmente varíe a través de él.

## Relaciones

- Un **Module** tiene exactamente una **Interface** (la superficie que presenta a callers y tests).
- **Depth** es propiedad de un **Module**, medida contra su **Interface**.
- Un **Seam** es donde vive la **Interface** de un **Module**.
- Un **Adapter** se sienta en un **Seam** y satisface la **Interface**.
- **Depth** produce **Leverage** para callers y **Locality** para mantenedores.

## Framings rechazados

- **Depth como ratio de líneas-implementación a líneas-interface** (Ousterhout): premia rellenar la implementación. Usamos depth-como-leverage en cambio.
- **"Interface" como la palabra clave `interface` de TypeScript o los métodos públicos de una clase**: demasiado estrecho — interface aquí incluye cada hecho que un caller debe saber.
- **"Boundary"**: sobrecargado con bounded context de DDD. Di **seam** o **interface**.
