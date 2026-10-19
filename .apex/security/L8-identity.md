---
layer: L8
title: Identity
status: passed
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI03
  - ASI10
evidence:
  - "APEX no tiene sistema de identidad propio: el usuario se autentica en el OS (permisos de filesystem) + la configuracion MCP de Claude Code. Single-user local threat model: transporte stdio, un solo caller (mcp/apex_server.py:1962)."
  - "No API keys, no tokens, no sesiones de usuario. Nada que rotar ni revocar. El unico 'secreto' de la casa es el vault de Obsidian, cuya ruta sale de una variable de entorno (mcp/handlers/_common.py:38-40) y solo se escribe, nunca se lee."
  - "Identidad del proyecto activo: `_find_project_root()` (mcp/apex_server.py:309-329) sube desde el cwd buscando `.apex/` o `.git/` y se DETIENE antes de `~` (mcp/apex_server.py:318-322). `_get_db()` compara la ruta resultante con la BD global y lanza NotAnApexProjectError si no hay `.apex/` propio (mcp/apex_server.py:339-354). Evita escribir en el proyecto equivocado."
  - "La memoria global `~/.apex/context.db` NUNCA se resuelve como proyecto: es append-only, solo de errores graves (lib/global_memory.py:25-42, lib/global_memory.py:56-95) y el servidor se niega a usarla como contexto (mcp/apex_server.py:346-353)."
  - "Sync a Obsidian usa el id del proyecto como partition key (mcp/handlers/_common.py:43-47), derivado del path de la BD con la misma formula que el scanner de apex-hub, y escribe en `projects/<id>/log.md` (mcp/handlers/_common.py:78-80). Evita cross-pollination entre proyectos del mismo vault."
  - "Audit trail: context.db guarda timestamps en todas las tablas con contenido (decisions.created_at, errors.created_at, components.last_modified, wiki_pages.created_at/updated_at, context_log.created_at) y la fase en decisions, errors, components y context_log (lib/context_db.py:62-121). `git log commands/ skills/` da la trazabilidad del prompt system."
---

# L8 — Identity

Protege: identidades de agentes, credenciales, permisos. Cubre ASI03
(Identity Abuse) y ASI10 (Rogue Agents).

Estado: **passed**. El threat model de esta capa es el de un sistema
mono-usuario local: la identidad es la del OS, la identidad de proyecto
la resuelve el servidor y no puede equivocarse, y la memoria global esta
separada del contexto de cada proyecto. Los controles de la plantilla
que tienen sentido en sistemas multi-credencial o multi-agente (JIT,
rotacion, revocacion) son N/A por diseno y quedan documentados como
tal. Queda un residual de baja severidad (F8-01).

## Checklist

Controles de la plantilla de la capa (`templates/apex-security/L8-identity.md`)
y las propiedades que si aplican a esta arquitectura:

- [x] **Threat model single-user local**: sin multi-tenancy, sin
      network-accessible API. Identidad = filesystem ownership. El
      transporte es stdio con un unico caller (mcp/apex_server.py:1962).
- [x] **Agent identity**: la identidad es la del propietario del
      fichero (permisos del OS). APEX no emite identidades, asi que no
      hay DID, public key ni API key que verificar: el unico actor es el
      caller de Claude Code.
- [x] **Project identity**: `_find_project_root` (mcp/apex_server.py:309-329)
      busca `.apex/` o `.git/` desde el cwd y para antes de `~`
      (mcp/apex_server.py:318-322); `_get_db()` lanza
      `NotAnApexProjectError` si el cwd no tiene `.apex/` propio o si la
      ruta resuelve a la BD global (mcp/apex_server.py:339-354). Ambas
      reglas evitan escrituras cruzadas entre proyectos.
- [x] **Separacion de la memoria global**: `~/.apex/context.db` es
      append-only de errores graves, con schema propio
      (lib/global_memory.py:25-42), y jamas se usa como contexto de
      proyecto (mcp/apex_server.py:346-353).
- [x] **Partition key del vault**: el id de proyecto se deriva del path de
      la BD con la misma formula que apex-hub
      (mcp/handlers/_common.py:43-47) y el log se escribe en
      `projects/<id>/log.md` (mcp/handlers/_common.py:78-80). Dos
      proyectos distintos no comparten log.
- [x] **Audit trail**: timestamps en todas las tablas con contenido y fase
      en decisions, errors, components y context_log
      (lib/context_db.py:62-121). `wiki_pages` tiene timestamps pero no
      columna de fase. `git log commands/ skills/` cubre el prompt system.
- [x] **JIT permissions**: N/A por diseno. No hay permisos granulares: todo
      o nada por stdio, con un unico caller. Si APEX evoluciona a modo
      network, hay que anadirlo (F8-02).
- [x] **Credential rotation**: N/A por diseno. No hay credenciales que
      rotar: ni API keys, ni tokens, ni sesiones de usuario.
- [x] **Revocation list**: N/A por diseno. APEX no emite identidades, asi
      que no hay identidades que revocar.
- [ ] **schema_version en project_meta (mejora opcional, F8-01)**: no
      esta escrito. Es una mejora de diagnostico, no un control de
      identidad, asi que no bloquea la capa.

## Findings abiertos

1. **F8-01 (baja)**: `apex_version` + `schema_version` en
   `project_meta` (lib/context_db.py:46-50), para detectar que el schema
   cambio sin migracion. Evidencia que lo cerraria: la clave escrita al
   inicializar el proyecto y su comparacion al abrir la BD, con aviso
   cuando no cuadre.
2. **F8-02 (media)**: si en el futuro APEX expone un socket de red
   (HTTP para dashboard remoto, por ejemplo), exigir OAuth + scopes por
   tool. Evidencia que lo cerraria: la decision documentada de no abrir
   un socket, revisada si aparece.

## Verificacion reproducible (2026-10-19)

```bash
# La resolucion de proyecto nunca sube a ~
sed -n '309,329p' mcp/apex_server.py
# Y el servidor se niega a servir una BD que no sea del proyecto
sed -n '339,354p' mcp/apex_server.py
# La memoria global es append-only de errores graves
sed -n '25,42p' lib/global_memory.py
sed -n '56,95p' lib/global_memory.py
# Partition key del vault
sed -n '43,47p' mcp/handlers/_common.py
# Audit trail: timestamps y fase
sed -n '62,121p' lib/context_db.py
```
