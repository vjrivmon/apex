---
layer: L1
title: Ingestion
status: partial
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI01
  - ASI04
evidence:
  - "Threat model: el servidor MCP habla JSON-RPC sobre stdio (mcp/apex_server.py:2158) y su unico caller es el Claude Code del propio usuario. No hay listener de red: lo unico que se lanza es el dashboard local del hub, con binario y cwd fijos (mcp/apex_server.py:191-197) y solo al arrancar el server (mcp/apex_server.py:2153-2156)."
  - "Ingestion sin red: lib/ingest.py recorre ficheros locales con source_dir.glob (lib/ingest.py:407) y filtra por extension (.md, .markdown, .txt, .json) en lib/ingest.py:405. Las URLs solo se EXTRAEN como texto con la regex lib/ingest.py:44; no hay fetch remoto."
  - "SQL parametrizado: las queries de lib/context_db.py que tocan datos variables usan placeholders `?` (lib/context_db.py:439, lib/context_db.py:655, lib/context_db.py:1212, lib/context_db.py:1235, lib/context_db.py:1315). Las f-strings existentes solo concatenan placeholders o nombres de tabla/columna internos, nunca input de usuario (lib/context_db.py:1173, lib/lint.py:139, lib/lint.py:189, lib/lint.py:281, lib/advisor.py:251, lib/db_compact.py:82)."
  - "Wiki scaffold: solo escribe ficheros .md dentro de .apex/. El slug se valida en un UNICO punto, `sanitize_slug()` (lib/wiki_scaffold.py:85), que rechaza `..`, separadores de ruta, caracteres de control, rutas absolutas y longitud excesiva; y `wiki_page_path()` (lib/wiki_scaffold.py:185) comprueba que la ruta RESUELTA (symlinks incluidos) queda dentro del wiki con `is_relative_to()`. `apex_wiki_add` valida antes de tocar BD o disco (mcp/handlers/wiki.py:77). F1-03 cerrado."
  - "Superficie de tools: 64 tools MCP al 2026-10-19, valor derivado de `len(await list_tools())` en mcp/apex_server.py:566-2087. No se hardcodea: recalcular con `grep -c '^        Tool($' mcp/apex_server.py` tras cada tool nueva."
  - "Ingestion acotada al proyecto: `apex_ingest_source` resuelve la ruta (relativa contra la raiz del proyecto; absoluta solo si cae dentro) y comprueba la ruta resuelta con `is_relative_to()` (mcp/handlers/wiki.py:26, mcp/handlers/wiki.py:34). Al ingerir un directorio, un symlink que apunta fuera se ignora con aviso (lib/ingest.py:397, lib/ingest.py:420). F1-04 cerrado."
  - "MCP audit: NO existe. El directorio .apex/raw/papers/ no existe en el repo, asi que el documento de superficie de ataque por tool que exige el checklist sigue pendiente (F1-02)."
---

# L1 — Ingestion

Protege: inputs del usuario, fuentes externas cargadas al agente, MCP
connectors. Cubre ASI01 (Goal Hijacking) y ASI04 (Supply Chain).

Estado: **partial**. Lo verificado en 2026-10-19 sostiene el threat model
local y el pipeline de ingesta sin red. Los dos hallazgos de path traversal
(F1-03, F1-04) se cerraron el 2026-10-19. Quedan un control sin implementar
(F1-01) y una laguna real en la superficie de tools (F1-02).

## Checklist

- [ ] **Input scanning** — no hay detector de prompt injection. No existe
      ningun modulo en `lib/` ni `mcp/` que inspeccione el texto ingerido:
      el pipeline solo extrae senales, URLs, wikilinks y heuristicas de
      exageracion (lib/ingest.py:87, lib/ingest.py:135). Mitigacion actual:
      el servidor MCP es local
      y su unico caller es el Claude Code del propio usuario. Riesgo real:
      texto hostil copiado de paginas web a `.apex/raw/research/*.md`, que
      luego alimenta `apex_synthesize`. Ver F1-01.
- [x] **Source verification** — `lib/ingest.py` solo lee ficheros locales y
      la tool MCP `apex_ingest_source` esta acotada al proyecto: las rutas
      relativas se resuelven contra la raiz del proyecto y las absolutas solo
      se aceptan si caen dentro (mcp/handlers/wiki.py:34). Un symlink que
      apunte fuera se ignora con aviso (lib/ingest.py:420). Cerrado 2026-10-19.
- [x] **Parametrized SQL** en las queries que reciben datos variables
      (ver evidence). Las f-strings que quedan son de placeholders
      internos, no de input de usuario.
- [ ] **MCP audit** — pendiente. No hay documento formal de superficie de
      ataque por tool. El numero de tools se deriva de
      `list_tools()` (mcp/apex_server.py:566-2087). Ver F1-02.
- [x] **Rate limiting** — N/A por diseno: el transporte es stdio local, un
      solo caller, sin red. Documentado como intencional.
- [x] **File type whitelist** — la ingesta filtra extensiones
      (lib/ingest.py:405) y el wiki scaffold solo escribe `.md`. El slug se
      valida en `sanitize_slug()` (lib/wiki_scaffold.py:85) y la ruta
      resultante se comprueba con `is_relative_to()` sobre la ruta resuelta
      (lib/wiki_scaffold.py:185). Cerrado 2026-10-19.

## Findings abiertos

1. **F1-01 (media)**: detector de prompt injection en `lib/ingest.py` antes
   de procesar ficheros de `raw/research/`. Evidencia que lo cerraria:
   modulo con los patrones de la checklist, unit tests con un prompt
   inyectado conocido, y el ingest rechaza o marca la pagina.
2. **F1-02 (baja)**: `.apex/raw/papers/mcp-audit-apex.md` con superficie y
   riesgo por tool. Evidencia que lo cerraria: un fichero por tool
   (`apex_wiki_add`, `apex_ingest_source`, `apex_scaffold_devops`,
   `apex_portfolio_draft`, `apex_browser_trace`, `apex_research_competitor`,
   `apex_install_roles`, `apex_skill_forge_approve`, ...) con su risk level
   y su superficie de escritura.
3. **F1-03 (media) — CERRADO 2026-10-19**. `apex_wiki_add` escribia
   `.apex/wiki/<slug>.md` con el slug del caller sin sanitizar, y un slug con
   `..` salia de `.apex/wiki`. Ahora `sanitize_slug()`
   (lib/wiki_scaffold.py:85) rechaza `..`, separadores, caracteres de control,
   rutas absolutas y longitud excesiva, y `wiki_page_path()`
   (lib/wiki_scaffold.py:185) comprueba que la ruta resuelta queda dentro del
   wiki. Test: `tests/test_wiki_path_safety.py` (35 tests, incluido el intento
   de `../../../etc/pwned`).
4. **F1-04 (media) — CERRADO 2026-10-19**. `apex_ingest_source` aceptaba
   paths absolutos fuera del proyecto. Ahora la ruta se resuelve y se
   comprueba con `is_relative_to()` sobre la ruta resuelta
   (mcp/handlers/wiki.py:26, mcp/handlers/wiki.py:34), y al ingerir un
   directorio los symlinks que apuntan fuera se ignoran con aviso
   (lib/ingest.py:420). Test: intento de ingerir `/etc/passwd`.

## Verificacion reproducible (2026-10-19)

```bash
# Sin fetch remoto en la ingesta
grep -nE "import (urllib|requests|httpx|aiohttp)" lib/ingest.py     # 0
# Sin eval/exec
grep -rnE "(^|[^._a-zA-Z0-9])(eval|exec)\(" lib/ mcp/               # 0
# Superficie de tools MCP
grep -c '^        Tool($' mcp/apex_server.py                          # 64
# Extensiones ingeridas
sed -n '405p' lib/ingest.py
# Validacion del slug (debe lanzar WikiPathError)
cd /home/vicente/RoadToDevOps/apex && .venv/bin/python3 -c "\
import sys; sys.path.insert(0,'lib')\
from wiki_scaffold import sanitize_slug, WikiPathError\
try:\
    sanitize_slug('../../etc/pwned')\
    print('FALLO: deberia rechazar')\
except WikiPathError as e:\
    print('OK:', e)"
# La ingesta acotada al proyecto
sed -n '34p' mcp/handlers/wiki.py
```
