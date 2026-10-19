---
description: Registrar una decisión en el contexto de APEX
argument-hint: "categoria,decision[,razonamiento]"
allowed-tools: mcp__apex__apex_add_decision
---

# /apex:decision — Registrar decisión

Registra una decisión en `.apex/context.db` con susrazones.

## Uso

```
/apex:decision architecture,usar SQLite en vez de Postgres,no hay servidor gestionado en el entorno
```

`$ARGUMENTS` se parsea por comas:

| Posición | Campo        | Obligatorio |
|----------|--------------|-------------|
| 1        | `category`   | si          |
| 2        | `decision`   | si          |
| 3        | `reasoning`  | no          |

Si falta el campo `decision`, NO inventes nada: pregunta al usuario qué
decisión se está tomando y por qué.

## Ejecución

1. Parsea `$ARGUMENTS` por `,` (recorta espacios; no dividas dentro de un
   campo salvo que el usuario lo pida explícitamente).
2. Llama a la tool:

```
mcp__apex__apex_add_decision(
    category="<category>",
    decision="<decision>",
    reasoning="<reasoning>",
)
```

3. Confirma en una línea qué se ha registrado (categoría + decisión corta).

## Notas

- Una decisión es un **hecho temporal**: si más adelante deja de ser cierta,
  se invalida con `mcp__apex__apex_invalidate_decision` en vez de borrarla.
- Registra la decisión **cuando se toma**, no al final de la sesión.
