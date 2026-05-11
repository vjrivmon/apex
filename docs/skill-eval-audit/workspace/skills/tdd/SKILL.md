---
name: tdd
description: Desarrollo guiado por tests con bucle red-green-refactor. Usar cuando el usuario quiere construir features o arreglar bugs usando TDD, menciona "red-green-refactor", quiere tests de integración, o pide desarrollo test-first. Triggers ES/EN — tdd, test-driven, "primero test", red-green-refactor, "tests integración".
---

# Test-Driven Development

## Filosofía

**Principio núcleo**: los tests verifican comportamiento a través de interfaces públicas, no detalles de implementación. El código puede cambiar entero; los tests no deberían.

**Buenos tests** son estilo integración: ejercitan rutas de código reales a través de APIs públicas. Describen *qué* hace el sistema, no *cómo* lo hace. Un buen test se lee como una especificación — "user can checkout with valid cart" te dice exactamente qué capacidad existe. Estos tests sobreviven refactors porque no les importa la estructura interna.

**Malos tests** están acoplados a la implementación. Mockean colaboradores internos, prueban métodos privados o verifican por medios externos (consultando la base de datos directamente en lugar de usar la interface). Señal de alarma: tu test rompe cuando refactorizas pero el comportamiento no ha cambiado. Si renombras una función interna y los tests fallan, esos tests probaban implementación, no comportamiento.

Ver [tests.md](tests.md) para ejemplos y [mocking.md](mocking.md) para directrices de mocking.

## Anti-patrón: rebanadas horizontales

**NO escribas todos los tests primero, luego toda la implementación.** Esto es "rebanado horizontal" — tratar RED como "escribir todos los tests" y GREEN como "escribir todo el código".

Esto produce **tests basura**:

- Tests escritos en bloque prueban comportamiento *imaginado*, no *real*
- Acabas probando la *forma* de las cosas (estructuras de datos, firmas de funciones) en lugar del comportamiento que ve el usuario
- Los tests se vuelven insensibles a cambios reales — pasan cuando el comportamiento rompe, fallan cuando está bien
- Adelantas a tus faros, comprometiéndote con una estructura de tests antes de entender la implementación

**Aproximación correcta**: rebanadas verticales vía tracer bullets. Un test → una implementación → repite. Cada test responde a lo que aprendiste del ciclo previo. Como acabas de escribir el código, sabes exactamente qué comportamiento importa y cómo verificarlo.

```
MAL (horizontal):
  RED:   test1, test2, test3, test4, test5
  GREEN: impl1, impl2, impl3, impl4, impl5

BIEN (vertical):
  RED→GREEN: test1→impl1
  RED→GREEN: test2→impl2
  RED→GREEN: test3→impl3
  ...
```

## Workflow

### 1. Planificación

Al explorar el código, usa el glosario de dominio del proyecto para que los nombres de tests y el vocabulario de la interface coincidan con el lenguaje del proyecto, y respeta los ADRs en el área que tocas.

**Puente APEX**: si el proyecto tiene `wiki/decisions/`, léelas antes de escribir tests. Si tiene `CONTEXT.md`, usa su vocabulario.

Antes de escribir código:

- [ ] Confirmar con el usuario qué cambios de interface hacen falta
- [ ] Confirmar con el usuario qué comportamientos testear (priorizar)
- [ ] Identificar oportunidades para [deep modules](deep-modules.md) (interface pequeña, implementación profunda)
- [ ] Diseñar interfaces para [testabilidad](interface-design.md)
- [ ] Listar los comportamientos a testear (no pasos de implementación)
- [ ] Conseguir aprobación del usuario sobre el plan

Pregunta: "¿Cómo debería verse la interface pública? ¿Qué comportamientos son los más importantes a testear?"

**No puedes testear todo.** Confirma con el usuario exactamente qué comportamientos importan más. Concentra el esfuerzo de testing en rutas críticas y lógica compleja, no en cada caso límite posible.

### 2. Tracer Bullet

Escribe UN test que confirme UNA cosa sobre el sistema:

```
RED:   Escribe test del primer comportamiento → test falla
GREEN: Escribe el mínimo código para pasar → test pasa
```

Este es tu tracer bullet — prueba que el camino funciona end-to-end.

### 3. Bucle incremental

Para cada comportamiento restante:

```
RED:   Escribe siguiente test → falla
GREEN: Mínimo código para pasar → pasa
```

Reglas:

- Un test cada vez
- Sólo el código suficiente para pasar el test actual
- No anticipes futuros tests
- Mantén los tests enfocados en comportamiento observable

### 4. Refactor

Tras pasar todos los tests, busca [candidatos de refactor](refactoring.md):

- [ ] Extraer duplicación
- [ ] Profundizar módulos (mover complejidad detrás de interfaces simples)
- [ ] Aplicar SOLID donde sea natural
- [ ] Considerar qué revela el nuevo código sobre el código existente
- [ ] Correr los tests tras cada paso de refactor

**Nunca refactorices en RED.** Llega a GREEN primero.

## Checklist por ciclo

```
[ ] Test describe comportamiento, no implementación
[ ] Test usa sólo interface pública
[ ] Test sobreviviría a un refactor interno
[ ] Código es mínimo para este test
[ ] No se han añadido features especulativas
```
