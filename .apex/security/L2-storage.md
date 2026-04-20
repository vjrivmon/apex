---
layer: L2
title: Storage
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI06
evidence:
  - "Almacén: SQLite local por proyecto en `.apex/context.db` (aiosqlite + WAL). Contenido: decisiones, errores, componentes, wiki pages, next_steps, session logs."
  - "No se almacenan credenciales, tokens ni PII: APEX nunca pide login, no guarda API keys. Los secrets (.env) viven en cada proyecto, gitignored."
  - "WAL mode activo (context.db-wal + context.db-shm presentes). ACID garantizado en concurrencia."
  - "Temporal facts (patrón Graphiti): invalid_from + superseded_by (lib/context_db.py:256). Nunca se borra información histórica, solo se marca invalidada."
  - "Backups: confiados al usuario (ninguna rutina automática). Recomendación en fase 14 del /apex."
---

# L2 — Storage

Protege: context.db, memoria persistente del agente, secrets. Cubre
ASI06 (Memory Poisoning).

## Checklist

- [x] **Datos no sensibles**: el modelo de datos no contiene
      credenciales, tokens ni PII del usuario final. Solo metadatos de
      desarrollo.
- [ ] **Cifrado at-rest**: N/A por diseño (no hay datos sensibles). Si
      un proyecto decide almacenar algo sensible en
      `apex_wiki_add(content=...)`, debe cifrarlo antes el usuario.
      FINDING documentado.
- [x] **Write control**: todas las escrituras pasan por `ApexContextDB`
      con parametrized SQL. Sin acceso directo externo.
- [x] **Temporal facts / audit trail**: decisiones invalidables con
      `invalid_from` + `superseded_by`. Errores con `recurrence_count`.
      Sessions con timestamps.
- [ ] **Backups probados**: no automatizados. Depende del
      usuario/proyecto (fase 14 manual).
- [x] **Database journaling**: WAL + SHM activos.

## Findings abiertos

1. **F2-01 (media)**: añadir rutina opcional `apex_backup(project)` que
   haga snapshot de `context.db` a `.apex/backups/YYYY-MM-DD.db` antes
   de synthesis/dream_deep.
2. **F2-02 (baja)**: en README.md del security directory, documentar
   expresamente que `apex_wiki_add(content=...)` NO debe contener
   secretos. Añadir pre-check en el tool.

## Evidencia complementaria

```yaml
evidence:
  - "Temporal facts pattern: context_db.py:256 UPDATE decisions SET invalid_from=datetime('now')"
  - "WAL: archivos context.db-wal/shm presentes en .apex/"
  - "No-secrets policy: grep de 'password|token|secret' en schema.sql devuelve 0"
```
