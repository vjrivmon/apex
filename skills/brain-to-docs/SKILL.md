---
name: brain-to-docs
description: Extrae la visión, decisiones y preferencias del usuario de su cabeza a documentación clara (README + wiki/decisions/) mediante un bucle de preguntas y respuestas. Actualiza el doc tras CADA respuesta. Triggers ES/EN — brain-to-docs, "saca la visión", "documenta este proyecto", "construye los docs", extract the vision, build out the docs.
---

# brain-to-docs

Adaptado de `davidondrej/skills` (MIT). El propósito: extraer todo el criterio,
juicio, conocimiento, visión, preferencias y decisiones del usuario a texto —
guardado como Markdown claro y conciso. El README lleva la visión; las
decisiones van a `wiki/decisions/` (o `docs/adr/` si el proyecto no es APEX).

## Cuándo se invoca

- El usuario quiere volcar la visión de un proyecto a documentación durable.
- Arranque de un proyecto donde la cabeza del usuario tiene más contexto que
  el código todavía.
- Complementa la Fase 0 socrática: donde socratic cuestiona el problema,
  brain-to-docs captura las respuestas en artefactos que sobreviven la sesión.

## El bucle

1. **Lee los docs primero, cada vez.** Antes de nada, lee `wiki/decisions/`
   (o `docs/adr/`) y `README.md` — otros agentes y el usuario editan estos
   archivos constantemente. No pisar contexto ajeno.
2. **Haz 5 preguntas distintas** en texto plano (nunca una UI de preguntas) —
   5 por defecto salvo que el usuario pida otro número. De alta variedad:
   ángulos únicos y creativos, no todas del mismo tipo (no todas de "stack" ni
   todas de "producto"). Excepción: si el usuario pide un foco concreto,
   síguelo. El usuario responde las que le resulten más útiles.
3. **Actualiza los docs tras CADA respuesta** — sin excepción. Tú decides si
   la respuesta actualiza `README.md` o se convierte en una decisión en
   `wiki/decisions/` — lo que tenga sentido.
4. Repite hasta que el usuario diga "ya está" (o similar).

## Reglas

- Todas las respuestas durante el proceso deben ser MUY CONCISAS, frases
  CORTAS, en lenguaje llano. Sin emojis, español con tildes.
- **Orden estricto**: recibe respuesta → actualiza el archivo → recién entonces
  la siguiente pregunta. Nunca al revés (si no, el doc se desincroniza).
- **Parchea, no reescribas.** Tras el esqueleto inicial, edita secciones
  concretas preservando las palabras del usuario. Nunca sobrescribas el archivo
  entero.
- **Las listas del usuario son conjuntos, no rankings.** Si responde "A, B, C",
  eso es un conjunto no ordenado. No infieras prioridad del orden; si necesitas
  rango, pregúntalo explícitamente.
- Decisiones en `wiki/decisions/`: formato APEX `YYYY-MM-DD-slug.md` con
  Estado + Contexto + Decisión + Consecuencias. Si el proyecto no es APEX y
  usa `docs/adr/`, numeración secuencial `NNNN-slug.md`.
- README: solo visión. Las decisiones van a las decisiones, no al README.
- No cuestiones el pensamiento del usuario salvo que lo pida, o esté cometiendo
  un error grave (ahí sí: regla absoluta 21, mantén tu criterio verificado).

## Puente APEX

- Persiste con `apex_add_decision` además de escribir el `.md`, para que el
  grader y el retrieval cross-project vean la decisión.
- Solo ofrece registrar una decisión (ADR) cuando es difícil de revertir,
  sorprendente sin contexto, y resultado de un trade-off real (mismo criterio
  que `grill-with-docs`). Si falta uno de los tres, no es un ADR.
- Emparéjalo con `grill-with-docs` para estresar el plan, y con `second-brain`
  para promover señales a memoria permanente.
