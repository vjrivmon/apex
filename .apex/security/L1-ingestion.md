---
layer: L1
title: Ingestion
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI01
  - ASI04
evidence:
  - "Threat model: APEX es un MCP server sobre stdio, invocado SOLO por el propietario de la máquina (Claude Code user). Sin exposición de red externa. Inputs externos controlados: texto desde el usuario vía herramientas MCP + ficheros del proyecto actual (`.apex/raw/`)."
  - "Parametrized SQL en 100% de las queries (lib/context_db.py:171,184,201,206,210,248,256,297,347,352,404,421,439,452,455,484,497,906,945). Zero f-string SQL. Zero string concat en SELECTs."
  - "Pipeline de ingesta (lib/ingest.py) extrae señales sólo con regex `http(s)://…` + markdown parsing. No ejecuta código descargado ni hace fetch remoto — solo lee archivos locales en `.apex/raw/`."
  - "Wiki scaffold (lib/wiki_scaffold.py) usa sólo Path.mkdir/write_text sobre paths derivados de `Path.cwd()`. No concatena inputs del usuario a rutas del filesystem sin sanitizar."
---

# L1 — Ingestion

Protege: inputs del usuario, fuentes externas cargadas al agente, MCP
connectors. Cubre ASI01 (Goal Hijacking) y ASI04 (Supply Chain).

## Checklist

- [ ] **Input scanning** — prompt injection detector activo en todo
      input del usuario. **FINDING**: no hay detector formal. Mitigación
      parcial: MCP server es local y el único caller es Claude Code del
      propio usuario. Riesgo principal: texto hostil copiado desde
      páginas web al `raw/research/*.md` que luego alimenta synthesis.
- [x] **Source verification** — el pipeline sólo procesa ficheros
      dentro del proyecto (`.apex/raw/`). No fetch remoto arbitrario.
- [x] **Parametrized SQL** en todas las queries (ver evidence).
- [ ] **MCP audit** — APEX expone 21 tools. Falta documento formal con
      surface area + riesgos por tool en
      `.apex/raw/papers/mcp-audit-apex.md`.
- [ ] **Rate limiting** — no aplica en stdio local. Documentado como
      intencional.
- [x] **File type whitelist** — wiki scaffold solo escribe `.md`;
      ingest sólo lee `.md` y `.txt` en `.apex/raw/`.

## Findings abiertos

1. **F1-01 (media)**: añadir detector de prompt injection en
   `lib/ingest.py` antes de procesar archivos de `raw/research/` que
   puedan venir de webs externas.
2. **F1-02 (baja)**: escribir `mcp-audit-apex.md` con análisis por tool
   de superficie + posibles abusos.

## Evidencia complementaria

```yaml
evidence:
  - "SQL parametrizado: 26 ocurrencias de `?` placeholder en context_db.py, 0 f-string SQL"
  - "Ingest pipeline: lib/ingest.py solo glob local + regex extract, zero urllib/requests"
  - "MCP stdio transport: sin network surface, threat model single-user local"
```
