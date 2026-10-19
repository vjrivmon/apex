---
name: iterate
description: Guía las fases intermedias 12-14 de /apex sobre un proyecto ya implementado — añadir feature, corregir bug, mejorar rendimiento, refactorizar o actualizar dependencias sin romper el hilo. Triggers ES/EN — iterar, iterate, nueva feature, arreglar bug, refactor, mejora, mantenimiento.
---

# IterationGuide — Guía para Fases Intermedias (12-14)

## Cuándo activar

Cuando el proyecto ya está implementado (fases 0-11 completadas o parciales) y
el usuario quiere:

- Añadir una nueva funcionalidad
- Corregir un bug
- Mejorar rendimiento
- Refactorizar algo
- Actualizar dependencias

## El problema que resuelve

MVP-Mode se quedaba corto aquí. Después del scaffolding inicial, Claude Code iba
a ciegas. IterationGuide usa context.db para saber exactamente dónde estás.

## Flujo para nueva funcionalidad

1. **Leer contexto**: `get_context("timeline")` para entender el estado
2. **Evaluar impacto**: ¿Qué componentes afecta? ¿Qué tests se romperán?
3. **Consultar errores**: ¿Hemos cometido errores similares antes?
4. **Preguntar al usuario**: ¿Es esto una iteración pequeña o grande?
5. **Planificar**: Si grande → mini-SPEC. Si pequeña → directo a implementar.
6. **Implementar**: Con verificación de que los tests siguen pasando
7. **Registrar**: Actualizar context.db con decisiones, errores, componentes

## Flujo para bug fix

1. **Leer contexto**: Buscar en context.db si el bug está relacionado con
   errores conocidos
2. **Diagnosticar**: Leer el código relevante, no adivinar
3. **Corregir**: Fix mínimo, no refactorizar de paso
4. **Registrar error**: add_error() con causa, fix, y lección
5. **Test**: Verificar que el fix no rompe nada

## Flujo para mejora de rendimiento

1. **Medir primero**: No optimizar sin datos
2. **Identificar cuello de botella**: Profiling, no intuición
3. **Proponer al usuario**: ¿El beneficio justifica la complejidad?
4. **Implementar**: De forma incremental
5. **Medir después**: Verificar que mejoró

## Reglas

- SIEMPRE leer context.db antes de actuar
- SIEMPRE registrar qué se hizo y por qué
- NUNCA refactorizar "de paso" durante un bug fix
- NUNCA optimizar sin medir primero
- Preguntar al usuario si es iteración grande o pequeña
