---
layer: L2
title: Storage
status: partial
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI06
evidence:
  - "Almacen por proyecto: SQLite en .apex/context.db, una BD por proyecto (mcp/apex_server.py:346-354). El schema (27 CREATE TABLE, una de ellas virtual FTS5) esta en lib/context_db.py:42-417 y no tiene ninguna columna de credencial, token ni PII."
  - "Journaling: PRAGMA journal_mode=WAL en lib/context_db.py:43, con busy_timeout a 5000 ms en lib/context_db.py:44. Los sidecars -wal/-shm se reparan solos si aparecen como symlinks rotos (mcp/apex_server.py:357-393), y la curacion se llama antes del primer connect (mcp/apex_server.py:404-411)."
  - "Temporal facts: las decisiones se invalidan sin borrar nada: UPDATE decisions SET invalid_from=datetime('now'), superseded_by=? WHERE id=? (lib/context_db.py:524-525). Los errores llevan recurrence_count y last_seen (lib/context_db.py:85-86)."
  - "Memoria global append-only: ~/.apex/context.db solo registra errores GRAVES (severity critical|high) de cualquier proyecto (lib/global_memory.py:45-49, lib/global_memory.py:56-95) y lo invoca el handler de errores (mcp/handlers/decisions.py:38-43). NUNCA se resuelve como proyecto: _get_db() compara la ruta con la global y lanza NotAnApexProjectError si coincide o si falta .apex/ propio (mcp/apex_server.py:346-353)."
  - "Backups: NO hay rutina automatica. Lo unico que hay es compactado con VACUUM (lib/db_compact.py:101), que no es un backup. El backup depende del usuario/proyecto (F2-01)."
---

# L2 — Storage

Protege: context.db, memoria persistente del agente, secrets. Cubre
ASI06 (Memory Poisoning).

Estado: **partial**. Todo lo que afirma la capa se ha verificado contra el
codigo actual, pero quedan dos controles sin implementar: backups
automatizados (F2-01) y pre-check de secretos en el contenido del wiki
(F2-02). El cifrado at-rest sigue siendo N/A por diseno: no se guardan
secretos, y quien meta uno lo hace en texto plano en `wiki_pages.content`.

## Checklist

- [x] **Datos no sensibles**: el schema (lib/context_db.py:42-417) no tiene
      columnas de credenciales, tokens ni PII. Solo metadatos de
      desarrollo. El unico contenido libre es `wiki_pages.content`, que
      escribe el usuario (F2-02).
- [ ] **Cifrado at-rest**: N/A por diseno (no hay datos sensibles). Si un
      proyecto decide meter algo sensible en `apex_wiki_add(content=...)`,
      queda en texto plano en `.apex/context.db` y en el `.md` del wiki.
      FINDING documentado (F2-02).
- [x] **Write control**: todas las escrituras pasan por `ApexContextDB`
      con SQL parametrizado (lib/context_db.py:439, lib/context_db.py:655,
      lib/context_db.py:1235). No hay acceso directo externo al fichero.
- [x] **Temporal facts / audit trail**: decisiones invalidables con
      `invalid_from` + `superseded_by` (lib/context_db.py:524-525). Errores
      con `recurrence_count` y `last_seen` (lib/context_db.py:85-86).
      Sesiones en `context_log` con `session_date` y `created_at`
      (lib/context_db.py:113-121).
- [x] **Separacion de la memoria global**: `~/.apex/context.db` es una
      memoria append-only de errores graves cross-project, con su propia
      tabla `grave_errors` (lib/global_memory.py:25-42). El servidor MCP
      se niega a usarla como proyecto (mcp/apex_server.py:346-353).
- [ ] **Backups probados**: no automatizados. Depende del
      usuario/proyecto. FINDING (F2-01).
- [x] **Database journaling**: WAL + SHM (lib/context_db.py:43) y
      self-heal de sidecars rotos (mcp/apex_server.py:357-393).

## Findings abiertos

1. **F2-01 (media)**: rutina opcional `apex_backup(project)` que haga
   snapshot de `context.db` a `.apex/backups/YYYY-MM-DD.db` antes de
   synthesis/dream_deep. Evidencia que lo cerraria: la funcion, un test
   que compruebe que el snapshot se crea y se puede reabrir, y una
   llamada desde `apex_synthesize`.
2. **F2-02 (baja)**: pre-check de secretos en `apex_wiki_add(content=...)`.
   Ya existe un detector de secretos reutilizable (`_SECRET_PATTERNS` en
   lib/library_ingest.py:66-75, aplicado en lib/library_ingest.py:270),
   pero solo se aplica a las skills externas que se proposean, no al wiki.
   Evidencia que lo cerraria: el mismo patron aplicado al contenido del
   wiki, con test que intente escribir `sk-ant-...` y vea la redaccion.
3. **F2-03 (baja, NUEVO)**: no hay deteccion de manipulacion de la BD
   (hash de `context.db` al arrancar). La plantilla de la capa lo pide
   (tamper detection) y no esta implementado. Evidencia que lo cerraria:
   hash SHA256 en `project_meta` comparado en el arranque, con aviso
   explicito cuando no cuadre.

## Verificacion reproducible (2026-10-19)

```bash
# WAL
sed -n '43,44p' lib/context_db.py
# Temporal facts
sed -n '524,525p' lib/context_db.py
# La memoria global nunca es un proyecto
sed -n '346,353p' mcp/apex_server.py
# No hay rutina de backup
grep -rni "backup" lib/ mcp/ --include=*.py    # solo menciones, ninguna rutina
# No hay columnas de credenciales: las unicas coincidencias son contadores
grep -niE "password|secret|api_key" lib/context_db.py   # 0
grep -niE "token" lib/context_db.py                      # solo contadores de tokens
```
