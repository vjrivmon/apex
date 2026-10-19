---
description: Registrar un componente del proyecto, con su fichero como contexto
argument-hint: "<id> <nombre> <tipo> @ruta/al/fichero"
allowed-tools: mcp__apex__apex_add_component
---

# /apex:component — Registrar componente

Registra en `.apex/context.db` una pieza del proyecto (módulo, servicio,
endpoint, librería) con su estado y sus dependencias.

## Uso

```
/apex:component auth-service servicio de autenticación backend @src/auth/service.py
```

| Posición | Campo   | Obligatorio |
|----------|---------|-------------|
| 1        | `id`    | si          |
| 2        | `nombre`| si          |
| 3        | `tipo`  | si          |
| 4        | `@ruta` | no          |

El `@ruta` es la referencia al fichero: Claude Code lo añade al contexto
antes de ejecutar el comando, así que no hace falta leerlo a mano.

## Ejecución

1. Determina el `id` en kebab-case a partir del nombre si el usuario no lo da
   explícitamente (ej. `auth-service`).
2. Determina el `tipo` (`backend`, `frontend`, `infra`, `lib`, `script`…) a
   partir de lo que se ve en el fichero. Si es ambiguo, pregunta.
3. Llama a la tool:

```
mcp__apex__apex_add_component(
    id="<id>",
    name="<nombre>",
    type="<tipo>",
    description="<descripcion corta de lo que hace>",
    files=["<ruta>"],
    phase=<fase actual>,
)
```

4. Confirma en una línea el componente registrado y su estado.

## Notas

- El estado se actualiza con `mcp__apex__apex_update_component`; no lo
  re-registres cada vez.
- Marca `verified` solo cuando el componente tiene tests que lo cubren.
