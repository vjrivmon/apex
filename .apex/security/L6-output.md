---
layer: L6
title: Output
status: partial
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI09
evidence:
  - "Outputs del MCP son JSON con campos estructurados (phases, decisions, errors, wiki_pages). Todas las tools devuelven TextContent con un dict serializado por el handler, no hay texto libre del modelo (mcp/handlers/context.py:35-42)."
  - "El MCP no tiene un LLM generativo dentro: es CRUD + FTS5. El unico modelo que consulta es el embedder local nomic-embed-text, via Ollama en localhost:11434 (lib/embeddings.py:44-60), que no genera texto de cara al usuario."
  - "Portfolio publisher (lib/portfolio_publish.py): genera MDX con frontmatter YAML serializado por yaml.safe_dump (lib/portfolio_publish.py:161-172) y escribe `<slug>.mdx.draft` mientras apply=False (lib/portfolio_publish.py:175-203). El handler tambien usa apply=False por default (mcp/handlers/portfolio.py:43)."
  - "Truncado de outputs: los resultados de busqueda se cortan a 150 caracteres (mcp/handlers/context.py:97), la leccion de un error a 200 (mcp/handlers/wiki.py:71), el resumen de sesion a 80 (mcp/handlers/context.py:117) y las lineas del log de Obsidian a 100 (mcp/handlers/_common.py:87). El payload de telemetria se corta a 500 (mcp/apex_server.py:243)."
  - "CORRECCION 2026-10-19: el truncado a 500 caracteres del resumen de wiki pages que afirmaba el informe de 2026-04-20 no existe. No hay ningun truncado a 500 sobre el contenido del wiki; los 500 de mcp/apex_server.py:243 son del payload de telemetria, no de una tool de lectura."
  - "Redaccion de credenciales: NO hay scanner en las outputs del MCP. Si existe un detector de secretos, pero solo se aplica a las skills externas que se proposean (lib/library_ingest.py:66-75, lib/library_ingest.py:270). Ver F6-01."
---

# L6 — Output

Protege: respuestas al usuario, prevencion de exfiltracion. Cubre
ASI09 (Human Trust Risk).

Estado: **partial**. La forma de las outputs es solida (tipadas, sin
texto libre del modelo, con truncado). El control que la plantilla pide
para esta capa —redaccion de credenciales en la salida— no existe (F6-01,
F6-02), y una afirmacion del informe de 2026-04-20 resulto ser falsa
(truncado a 500 del resumen de wiki).

## Checklist

- [x] **Schema-validated output**: todas las tools devuelven estructuras
      tipadas (dict con claves fijas) que el handler serializa a
      TextContent. No hay texto libre del LLM
      (mcp/handlers/context.py:35-42).
- [x] **No credentials en DB**: el schema (lib/context_db.py:42-417) no
      tiene columnas sensibles. Mitigacion parcial: el usuario puede
      filtrar un secreto en `wiki_pages.content` — depende de su
      autodisciplina (F6-02).
- [ ] **Credential redaction runtime**: no hay scanner automatico en las
      outputs. Si hay detector de secretos, pero solo en la ingesta de
      librerias externas (lib/library_ingest.py:66-75). FINDING (F6-01).
- [ ] **PII scanner**: no implementado. N/A para APEX mismo (no hay PII),
      pero relevante si un proyecto decide registrar tickets con datos de
      usuario en context.db. FINDING (F6-03).
- [ ] **Exfiltration detection**: no implementado. Parcialmente N/A: el
      MCP es local y no tiene superficie de red propia, pero las tools
      `apex_browser_trace` y `apex_research_competitor` salen a Internet
      con lo que el caller les pase (lib/browser_trace.py:176-212,
      lib/research.py:53-65). FINDING (F6-04).
- [x] **Output truncation**: verificado. 150 chars en busquedas
      (mcp/handlers/context.py:97), 200 en la leccion de error
      (mcp/handlers/wiki.py:71), 80 en el resumen de sesion
      (mcp/handlers/context.py:117) y 100 en el log de Obsidian
      (mcp/handlers/_common.py:87).
- [x] **Portfolio draft safety**: `apex_portfolio_draft(apply=false)` por
      default, y el generador escribe `.mdx.draft` hasta que se aplica
      (mcp/handlers/portfolio.py:43, lib/portfolio_publish.py:175-203).

## Findings abiertos

1. **F6-01 (media)**: `lib/output_guards.py` con regex basica para
   `sk-...`, `ghp_...`, `xoxb-...`, `AKIA...` en el contenido devuelto por
   `apex_get_context` y `apex_search`. El detector ya existe y esta probado
   en la ingesta de librerias (lib/library_ingest.py:66-75): falta
   reutilizarlo en la salida. Evidencia que lo cerraria: el modulo, su
   test, y la redaccion visible en el texto devuelto.
2. **F6-02 (baja)**: documentar en README.md el contrato de
   `apex_wiki_add`: el contenido NO debe incluir secretos, y el slug NO
   debe contener `..` (ver F1-03 en L1). Evidencia que lo cerraria: la
   nota en README.md mas un pre-check antes de escribir.
3. **F6-03 (baja, NUEVO)**: scanner de PII (email, DNI, IBAN, telefono,
   tarjeta) ausente. Relevante en cuanto un proyecto registre datos de
   usuario final en context.db. Evidencia que lo cerraria: el scanner con
   su test sobre una fila con PII.
4. **F6-04 (baja, NUEVO)**: deteccion de exfiltracion en las tools que
   salen a red. Con el caller local y unico, el riesgo real es bajo, pero
   no hay ninguna marca cuando `apex_browser_trace` o
   `apex_research_competitor` llevan contenido del proyecto a una URL
   externa. Evidencia que lo cerraria: log de destinations +
   confirmacion cuando el contenido viene de context.db.

## Verificacion reproducible (2026-10-19)

```bash
# Sin LLM generativo en el MCP
grep -rn "openai\|anthropic\|ollama" mcp/ --include=*.py        # solo el embedder
# Truncados reales
grep -rn "\[:150\]\|\[:200\]\|\[:100\]\|\[:80\]" mcp/handlers/
# apply=False por default en el portfolio
sed -n '43p' mcp/handlers/portfolio.py
sed -n '175p' lib/portfolio_publish.py
# Redaccion: solo en la ingesta de librerias
grep -rn "_SECRET_PATTERNS" lib/
```
