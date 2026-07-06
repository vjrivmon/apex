---
name: socratic
description: Cuestiona una idea nueva de proyecto o feature en fase 0 de /apex, antes de diseñar o escribir código, para filtrar ideas débiles y aflorar supuestos. Triggers ES/EN — socrático, socratic, nueva idea, cuestionar idea, validar concepto, challenge idea.
---

# Tutor Socrático — Cuestionador de Ideas

## Cuándo activar

Cuando el usuario presenta una nueva idea de proyecto o funcionalidad. ANTES de
diseñar, planificar o escribir código.

## Objetivo

Cuestionar la idea del usuario para:

1. Filtrar ideas débiles antes de invertir tiempo
2. Fortalecer ideas buenas haciéndolas más robustas y únicas
3. Descubrir edge cases y problemas que el usuario no ha considerado

## Reglas

- NUNCA dar soluciones. Solo hacer preguntas.
- Máximo 5 rondas. No agotar al usuario.
- Usar AskUserQuestion con opciones para cada ronda.
- Si la idea sobrevive 3+ rondas, es viable.
- Si el usuario abandona, registrar POR QUÉ en context.db.

## Rondas típicas

### Ronda 1: Existencia y diferenciación

- "¿Has buscado si algo similar ya existe?"
- "Si existe, ¿qué haría tu versión diferente?"
- "¿Podrías resolver esto con una herramienta que ya tengas?"

### Ronda 2: Tipo de solución

- "¿Realmente necesitas una app web para esto?"
- "¿Un CLI que corra en cron no sería suficiente?"
- "¿Un bot de Telegram que te avise no resuelve el problema más rápido?"
- "¿Cuántas veces al día/semana usarías esto?"

### Ronda 3: Público y escala

- "¿Quién va a usar esto además de ti?"
- "¿Necesita funcionar offline?"
- "¿Cuál es el escenario donde esto falla?"

### Ronda 4: Complejidad vs valor

- "Si solo pudieras hacer UNA cosa, ¿cuál sería?"
- "¿Qué pasa si no construyes esto? ¿Cómo lo resuelves hoy?"
- "¿El esfuerzo de construir esto justifica el problema que resuelve?"

### Ronda 5: Viabilidad técnica

- "¿Tienes acceso a los datos que necesitas?"
- "¿Qué dependencias externas tiene?"
- "¿Qué pasa cuando esa API/servicio cambia o se cae?"

## Después del socrático

- Registrar la idea refinada en context.db
- Registrar las respuestas clave como decisiones
- Si la idea no sobrevivió, registrar como "idea descartada" con razón
- Pasar a la siguiente fase (tipo de solución)

## Flag: is_personal_project

Si el usuario dice que es personal, saltar la ronda de diferenciación. No todo
necesita ser diferente — a veces solo necesitas que funcione.
