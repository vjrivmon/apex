---
layer: L5
title: Execution
status: partial
reviewed_by: "apex self-audit"
reviewed_at: "2026-04-20"
asi_coverage:
  - ASI02
  - ASI03
  - ASI05
evidence:
  - "APEX MCP server NO ejecuta código del usuario. No tiene eval/exec, no hay REPL ni playground."
  - "Outbound HTTP: cero. Ni urllib ni requests ni httpx importados en lib/. El pipeline de ingest (lib/ingest.py) solo lee archivos locales."
  - "Único subprocess: `_launch_hub_if_needed` (apex_server.py:106-130) con binario fijo y cwd fijo. No acepta argumentos del caller."
  - "Único outbound indirecto: Obsidian sync (apex_server.py:186) escribe a filesystem local (`~/Documents/ApexVault/`). Controlado por `_OBSIDIAN_VAULT.exists()`."
  - "Scanner de apex-hub (cuando se ejecuta) recorre `~/RoadToDevOps/*/.apex/context.db` en modo read-only."
---

# L5 — Execution

Protege: ejecución de código, llamadas a servicios externos. Cubre
ASI02, ASI03, ASI05.

## Checklist

- [x] **No code execution**: zero `eval()`, `exec()`, `compile()` en
      `lib/` y `mcp/`. Verificado con grep.
- [x] **No outbound HTTP**: zero imports de `requests`, `urllib.request`,
      `httpx`, `aiohttp` en `lib/`. Se mantiene offline-first.
- [x] **Subprocess allowlist**: 1 subprocess único (`_launch_hub_if_needed`)
      con binario e cwd fijos.
- [ ] **Resource budgets**: no hay `resource.setrlimit` aplicado. No
      crítico porque no ejecutamos código arbitrario, pero es buena
      práctica para `apex_ingest_source` ante archivos gigantes.
- [x] **Sandbox necesaria**: N/A (no se ejecuta código generado).
- [x] **Allowlist filesystem**: escrituras se limitan a `.apex/`,
      `.github/workflows/` (scaffold devops), `Dockerfile*` (scaffold),
      y `content/cases/*.mdx` (portfolio draft). Paths se derivan de
      argumentos validados (`Path().resolve()`), no concatenan strings.
- [ ] **Circuit breaker**: no implementado. Relevante si algún día se
      añaden llamadas a modelos remotos.

## Findings abiertos

1. **F5-01 (baja)**: añadir `resource.setrlimit(RLIMIT_AS, 512MB)` en
   el entrypoint de `apex_ingest_source` para proteger ante archivos
   `raw/` de tamaño extremo.
2. **F5-02 (baja)**: validar que `apex_scaffold_devops(target_dir=...)`
   rechaza paths absolutos fuera del proyecto actual o con `..` en el
   middle. Actual check: solo `Path(target).resolve()`.

## Evidencia complementaria

```yaml
evidence:
  - "grep -r 'eval\\|exec' lib/ mcp/ → 0 matches en runtime code"
  - "grep -r 'requests\\|urllib\\|httpx\\|aiohttp' lib/ → 0 matches"
  - "subprocess allowlist: apex_server.py:106-130"
```
