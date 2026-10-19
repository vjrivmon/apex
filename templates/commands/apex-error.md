---
description: Registrar un error en el contexto de APEX con el diff staged como contexto
argument-hint: "descripcion[,causa[,leccion]]"
allowed-tools: mcp__apex__apex_add_error, Bash(git diff:*)
---

# /apex:error — Registrar error

Registra en `.apex/context.db` un error (bug, sorpresa, casi-fallo) junto con
su causa y la lección que deja. Los errores con `recurrence_count` alto son
lo que alimenta el apex-doctor, así que registrarlos vale.

## Uso

```
/apex:error el parser de YAML fallaba con listas vacías,no contemplaba la lista vacia,validar el esquema antes de parsear
```

`$ARGUMENTS` se parsea por comas:

| Posición | Campo        | Obligatorio |
|----------|--------------|-------------|
| 1        | `descripcion` | si          |
| 2        | `causa`      | no          |
| 3        | `leccion`    | no          |

## Contexto previo

El diff de lo que está staged se inyecta antes de que el agente escriba, para
que la descripción no tenga que adivinar qué cambió:

!`git diff --staged`

## Ejecución

1. Lee el diff de arriba y contrasta con `$ARGUMENTS`.
2. Llama a la tool:

```
mcp__apex__apex_add_error(
    source="claude",
    description="<descripcion>",
    cause="<causa>",
    lesson="<leccion>",
)
```

3. Confirma en una línea el error registrado y la lección.

## Notas

- `source` distingue el origen: `"claude"` para fallos del agente,
  `"user"` para correcciones que ha pedido el usuario.
- Si el diff está vacío, no inventes un contexto: registra el error con lo
  que sepas y di que no había nada staged.
