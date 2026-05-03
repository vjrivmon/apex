# Deepening

Cómo profundizar un cluster de módulos shallow de forma segura, dadas sus dependencias. Asume el vocabulario de [LANGUAGE.md](LANGUAGE.md) — **module**, **interface**, **seam**, **adapter**.

## Categorías de dependencia

Al evaluar un candidato a profundizar, clasifica sus dependencias. La categoría determina cómo se testa el módulo profundizado a través de su seam.

### 1. In-process

Computación pura, estado en memoria, sin I/O. Siempre profundizable — fusiona los módulos y testea a través de la nueva interface directamente. No hace falta adapter.

### 2. Local-substitutable

Dependencias que tienen test stand-ins locales (PGLite para Postgres, fs en memoria). Profundizable si el stand-in existe. El módulo profundizado se testa con el stand-in corriendo en la suite. El seam es interno; sin port en la interface externa del módulo.

### 3. Remote pero owned (Ports & Adapters)

Tus propios servicios a través de un network boundary (microservicios, APIs internas). Define un **port** (interface) en el seam. El módulo deep posee la lógica; el transporte se inyecta como **adapter**. Los tests usan un adapter en memoria. Producción usa un adapter HTTP/gRPC/cola.

Forma de la recomendación: *"Define un port en el seam, implementa un adapter HTTP para producción y un adapter en memoria para test, de modo que la lógica vive en un único módulo deep aunque se despliegue a través de la red."*

### 4. True external (Mock)

Servicios de terceros (Stripe, Twilio, etc.) que no controlas. El módulo profundizado toma la dependencia externa como port inyectado; los tests proveen un mock adapter.

## Disciplina de seam

- **Un adapter significa seam hipotético. Dos adapters significa seam real.** No introduzcas un port a menos que al menos dos adapters estén justificados (típicamente producción + test). Un seam de un solo adapter es sólo indirección.
- **Internal seams vs external seams.** Un módulo deep puede tener internal seams (privados a su implementación, usados por sus propios tests) además del external seam en su interface. No expongas internal seams a través de la interface sólo porque los tests los usan.

## Estrategia de testing: reemplaza, no apiles

- Los unit tests viejos sobre módulos shallow se vuelven basura una vez existen tests en la interface del módulo profundizado — bórralos.
- Escribe nuevos tests en la interface del módulo profundizado. La **interface es la superficie de test**.
- Los tests assertan sobre outcomes observables a través de la interface, no sobre estado interno.
- Los tests deberían sobrevivir refactors internos — describen comportamiento, no implementación. Si un test tiene que cambiar cuando cambia la implementación, está testeando más allá de la interface.
