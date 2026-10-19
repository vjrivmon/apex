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
  - "Wiki scaffold: solo escribe ficheros .md dentro de .apex/ (lib/wiki_scaffold.py:94, lib/wiki_scaffold.py:150, lib/wiki_scaffold.py:205, lib/wiki_scaffold.py:345). PERO apex_wiki_add concatena el slug sin sanitizar: .apex/wiki/<slug>.md (mcp/handlers/wiki.py:33) permite traversal fuera de .apex/wiki. Ver F1-03."
  - "Superficie de tools: 64 tools MCP al 2026-10-19, valor derivado de `len(await list_tools())` en mcp/apex_server.py:566-2087. No se hardcodea: recalcular con `grep -c '^        Tool($' mcp/apex_server.py` tras cada tool nueva."
  - "MCP audit: NO existe. El directorio .apex/raw/papers/ no existe en el repo, asi que el documento de superficie de ataque por tool que exige el checklist sigue pendiente (F1-02)."
---

# L1 — Ingestion

Protege: inputs del usuario, fuentes externas cargadas al agente, MCP
connectors. Cubre ASI01 (Goal Hijacking) y ASI04 (Supply Chain).

Estado: **partial**. Lo verificado en 2026-10-19 sostiene el threat model
local y el pipeline de ingesta sin red, pero quedan tres controles sin
implementar (F1-01, F1-03, F1-04) y una laguna real en la superficie de
tools (F1-02).

## Checklist

- [ ] **Input scanning** — no hay detector de prompt injection. No existe
      ningun modulo en `lib/` ni `mcp/` que inspeccione el texto ingerido:
      el pipeline solo extrae senales, URLs, wikilinks y heuristicas de
      exageracion (lib/ingest.py:87, lib/ingest.py:135). Mitigacion actual:
      el servidor MCP es local
      y su unico caller es el Claude Code del propio usuario. Riesgo real:
      texto hostil copiado de paginas web a `.apex/raw/research/*.md`, que
      luego alimenta `apex_synthesize`. Ver F1-01.
- [ ] **Source verification** — parcial. `lib/ingest.py` solo lee ficheros
      locales, pero la tool MCP `apex_ingest_source` acepta CUALQUIER path
      absoluto, no solo `.apex/raw/` (mcp/handlers/wiki.py:90-95). Ver
      F1-04.
- [x] **Parametrized SQL** en las queries que reciben datos variables
      (ver evidence). Las f-strings que quedan son de placeholders
      internos, no de input de usuario.
- [ ] **MCP audit** — pendiente. No hay documento formal de superficie de
      ataque por tool. El numero de tools se deriva de
      `list_tools()` (mcp/apex_server.py:566-2087). Ver F1-02.
- [x] **Rate limiting** — N/A por diseno: el transporte es stdio local, un
      solo caller, sin red. Documentado como intencional.
- [ ] **File type whitelist** — parcial. La ingesta filtra extensiones
      (lib/ingest.py:405) y el wiki scaffold solo escribe `.md`, pero
      `apex_wiki_add` escribe `<slug>.md` con el slug sin sanitizar
      (mcp/handlers/wiki.py:33). Ver F1-03.

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
3. **F1-03 (media, NUEVO)**: `apex_wiki_add` escribe
   `.apex/wiki/<slug>.md` con el slug del caller sin sanitizar
   (mcp/handlers/wiki.py:33-35), y el schema del tool no impone patron
   (mcp/apex_server.py:901-913). Un slug con `..` sale de `.apex/wiki`.
   Evidencia que lo cerraria: validacion del slug contra una regex cerrada
   mas `page_path.resolve().is_relative_to(wiki_dir.resolve())`, con un
   test que intente `../../escapada`.
4. **F1-04 (media, NUEVO)**: `apex_ingest_source` acepta paths absolutos
   fuera del proyecto (mcp/handlers/wiki.py:90-95), asi que la superficie
   de ingestion no esta acotada a `.apex/raw/`. Evidencia que lo cerraria:
   restriccion explicita al project root (o a `.apex/raw/`) con test que
   intente ingerir `/etc/passwd`.

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
# Slug sin sanitizar en el wiki
sed -n '33p' mcp/handlers/wiki.py
```
