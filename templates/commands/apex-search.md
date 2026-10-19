---
description: Buscar en el contexto del proyecto (decisiones, errores, wiki)
argument-hint: "consulta"
allowed-tools: mcp__apex__apex_search, mcp__apex__apex_search_cross_project
---

# /apex:search — Buscar en el contexto

Busca en `.apex/context.db`: decisiones vigentes, errores registrados, wiki y
notas de sesión. Útil cuando sabes que el dato está en APEX pero no recuerdas
dónde.

## Uso

```
/apex:search por qué usamos retrieval híbrido
```

## Ejecución

1. Llama a la tool con la consulta literal:

```
mcp__apex__apex_search(query="$ARGUMENTS")
```

2. Si no hay resultados en el proyecto actual, prueba el agregado
   cross-project:

```
mcp__apex__apex_search_cross_project(query="$ARGUMENTS")
```

3. Presenta los resultados como lista: fuente, fecha y una línea de cada
   entrada. Cita la ruta del fichero cuando la haya.

## Notas

- `apex_search` usa recuperación híbrida (FTS5/BM25 + LIKE). No hace
  embeddings: para "buscar por significado" está la biblioteca de libros
  (`apex_book_search`), que sí usa vectores.
- Si la consulta está en inglés y el proyecto está en español, prueba las
  dos: el índice léxico no cruza idiomas.
