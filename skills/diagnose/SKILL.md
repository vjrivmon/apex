---
name: diagnose
description: Bucle de diagnóstico disciplinado para bugs difíciles y regresiones de rendimiento. Reproduce → minimiza → hipotetiza → instrumenta → corrige → test de regresión. Usar cuando el usuario dice "diagnose this" / "debug this", reporta un bug, dice que algo está roto/throwing/failing, o describe una regresión de rendimiento. Triggers ES/EN — diagnose, diagnostica, debug, "está roto", regresión, "no funciona".
---

# Diagnose

Disciplina para bugs difíciles. Salta fases sólo cuando esté justificado explícitamente.

Al explorar el código, usa el glosario de dominio del proyecto para tener un modelo mental claro de los módulos relevantes, y revisa los ADRs en el área que tocas.

**Puente APEX**: si existe `wiki/decisions/`, lee las decisiones que toquen el módulo donde está el bug. Si existe `CONTEXT.md`, usa su vocabulario para nombrar la hipótesis y el seam. Tras la fase 6, si el bug revela un problema arquitectónico, considera escribir una nota en `wiki/synthesis/` o disparar `apex_doctor_run` para detectar patrones cross-fase.

## Fase 1 — Construye un bucle de feedback

**Esto es la skill.** Todo lo demás es mecánico. Si tienes una señal pasa/falla rápida, determinista y ejecutable por el agente para el bug, encontrarás la causa — bisección, prueba de hipótesis e instrumentación todos consumen esa señal. Si no la tienes, ninguna cantidad de mirar código te salvará.

Gasta esfuerzo desproporcionado aquí. **Sé agresivo. Sé creativo. Niégate a rendirte.**

### Formas de construir uno — pruébalas más o menos en este orden

1. **Test que falla** en cualquier seam que alcance el bug — unit, integration, e2e.
2. **Curl / script HTTP** contra un dev server corriendo.
3. **Invocación CLI** con input de fixture, diffeando stdout contra un snapshot conocido.
4. **Script de navegador headless** (Playwright / Puppeteer) — conduce la UI, asserta sobre DOM/console/network.
5. **Reproducir un trace capturado.** Guarda un request real / payload / event log a disco; reprodúcelo a través del code path en aislamiento.
6. **Harness desechable.** Levanta un subset mínimo del sistema (un servicio, deps mockeadas) que ejercite el code path del bug con una sola llamada de función.
7. **Loop property / fuzz.** Si el bug es "a veces output incorrecto", corre 1000 inputs aleatorios y busca el modo de fallo.
8. **Harness de bisección.** Si el bug apareció entre dos estados conocidos (commit, dataset, versión), automatiza "boot en estado X, check, repite" para poder hacer `git bisect run`.
9. **Loop diferencial.** Corre el mismo input por la versión vieja vs la nueva (o dos configs) y diff outputs.
10. **Script HITL bash.** Último recurso. Si un humano tiene que clicar, condúcelo con `scripts/hitl-loop.template.sh` para que el loop siga estructurado. El output capturado realimenta al agente.

Construye el bucle de feedback correcto, y el bug está 90% arreglado.

### Itera sobre el bucle mismo

Trata el loop como un producto. Una vez tengas *un* loop, pregunta:

- ¿Puedo hacerlo más rápido? (Cachear setup, saltar init no relacionado, estrechar el scope del test.)
- ¿Puedo hacer la señal más nítida? (Asertar sobre el síntoma específico, no "no crashed".)
- ¿Puedo hacerlo más determinista? (Pinear tiempo, semilla RNG, aislar fs, congelar red.)

Un loop flaky de 30 segundos es apenas mejor que ninguno. Un loop determinista de 2 segundos es un superpoder de debugging.

### Bugs no deterministas

El objetivo no es un repro limpio sino una **tasa de reproducción más alta**. Bucle el trigger 100×, paraleliza, añade estrés, estrecha ventanas de timing, inyecta sleeps. Un bug 50%-flake es debuggeable; 1% no lo es — sigue subiendo la tasa hasta que sea debuggeable.

### Cuando genuinamente no puedas construir un loop

Para y dilo explícitamente. Lista lo que probaste. Pide al usuario: (a) acceso al entorno que lo reproduce, (b) un artefacto capturado (HAR, log dump, core dump, screen recording con timestamps), o (c) permiso para añadir instrumentación temporal en producción. **No** procedas a hipotetizar sin un loop.

No procedas a la Fase 2 hasta que tengas un loop en el que creas.

## Fase 2 — Reproduce

Corre el loop. Mira al bug aparecer.

Confirma:

- [ ] El loop produce el modo de fallo que **el usuario** describió — no un fallo distinto que pasa cerca. Bug equivocado = fix equivocado.
- [ ] El fallo es reproducible a través de múltiples runs (o, para no-deterministas, reproducible a una tasa lo bastante alta para debuggear).
- [ ] Has capturado el síntoma exacto (mensaje de error, output incorrecto, timing lento) para que las fases siguientes puedan verificar que el fix realmente lo aborda.

No procedas hasta reproducir el bug.

## Fase 3 — Hipotetiza

Genera **3-5 hipótesis ranqueadas** antes de testar cualquiera. La generación de una sola hipótesis ancla a la primera idea plausible.

Cada hipótesis debe ser **falsable**: enuncia la predicción que hace.

> Formato: "Si <X> es la causa, entonces <cambiar Y> hará desaparecer el bug / <cambiar Z> lo empeorará."

Si no puedes enunciar la predicción, la hipótesis es una vibración — descártala o afílala.

**Muestra la lista ranqueada al usuario antes de testar.** A menudo tienen conocimiento de dominio que reorganiza el ranking al instante ("acabamos de desplegar un cambio en #3"), o saben hipótesis que ya descartaron. Checkpoint barato, gran ahorro de tiempo. No te bloquees: procede con tu ranking si el usuario está AFK.

## Fase 4 — Instrumenta

Cada sonda debe mapear a una predicción específica de la Fase 3. **Cambia una variable a la vez.**

Preferencia de herramientas:

1. **Inspección con debugger / REPL** si el entorno lo soporta. Un breakpoint vence a diez logs.
2. **Logs dirigidos** en los bordes que distinguen hipótesis.
3. Nunca "loguea todo y grepea".

**Etiqueta cada log de debug** con un prefijo único, p.ej. `[DEBUG-a4f2]`. La limpieza al final se vuelve un único grep. Logs sin etiquetar sobreviven; logs etiquetados mueren.

**Rama perf.** Para regresiones de rendimiento, los logs suelen estar mal. En su lugar: establece una medición baseline (timing harness, `performance.now()`, profiler, query plan), después bisect. Mide primero, arregla después.

## Fase 5 — Fix + test de regresión

Escribe el test de regresión **antes del fix** — pero sólo si existe un **seam correcto**.

Un seam correcto es uno donde el test ejercita el **patrón real del bug** como ocurre en el call site. Si el único seam disponible es demasiado superficial (test single-caller cuando el bug requiere múltiples callers, unit test que no puede replicar la cadena que disparó el bug), un test de regresión ahí da falsa confianza.

**Si no existe seam correcto, eso mismo es el hallazgo.** Anótalo. La arquitectura del codebase está impidiendo que el bug quede atado en corto. Marca esto para la siguiente fase.

Si existe un seam correcto:

1. Convierte el repro minimizado en un test que falla en ese seam.
2. Mira cómo falla.
3. Aplica el fix.
4. Mira cómo pasa.
5. Re-ejecuta el loop de la Fase 1 contra el escenario original (no minimizado).

## Fase 6 — Limpieza + post-mortem

Requerido antes de declarar completado:

- [ ] El repro original ya no reproduce (re-corre el loop de la Fase 1)
- [ ] El test de regresión pasa (o la ausencia de seam queda documentada)
- [ ] Toda la instrumentación `[DEBUG-...]` eliminada (`grep` el prefijo)
- [ ] Prototipos desechables borrados (o movidos a una ubicación claramente marcada de debug)
- [ ] La hipótesis que resultó correcta se enuncia en el commit / PR — para que el siguiente debugger aprenda

**Después pregunta: ¿qué habría prevenido este bug?** Si la respuesta involucra cambio arquitectónico (sin buen seam de test, callers enredados, acoplamiento oculto) handoff al skill `/improve-codebase-architecture` con los detalles. Haz la recomendación **después** del fix, no antes — ahora tienes más información que cuando empezaste.

**Puente APEX**: este post-mortem es el momento ideal para `apex_add_error` (registrar el patrón en `context.db`) y, si se detecta recurrencia, dejar que `apex_doctor_run` lo recoja en el próximo análisis A1 (`override_clusters`).
