---
layer: L5
title: Execution
status: partial
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI02
  - ASI03
  - ASI05
evidence:
  - "APEX MCP server NO ejecuta codigo del usuario: cero llamadas a eval(), exec() o compile() en lib/ y mcp/ (los `compile` que existen son re.compile, p.ej. lib/ingest.py:44). No hay REPL ni sandbox de codigo generado."
  - "CORRECCION 2026-10-19: ya NO hay cero outbound HTTP. Cuatro rutas de red existen: el embedder local contra Ollama en localhost:11434 (lib/embeddings.py:44-60), el research de URLs arbitrarias con httpx (lib/research.py:53-65), la ingesta de librerías externas con urllib (lib/library_ingest.py:34-36) y la traza de navegador que lanza Chrome headless (lib/browser_trace.py:176-212)."
  - "CORRECCION 2026-10-19: ya NO hay un unico subprocess. Ademas del hub (mcp/apex_server.py:191-197) hay git en el grader (lib/grader.py:175-179), git en el reverse-engineer (lib/reverse_engineer.py:79-85), chromium en el research (lib/research.py:71-88), uvx en la ingesta de librerias (lib/library_ingest.py:444-457) y Chrome en la traza de navegador (lib/browser_trace.py:207-212)."
  - "Sin sandbox ni resource limits: no hay resource.setrlimit en lib/ ni mcp/, y el unico proceso que ejecuta codigo de terceros es Chrome headless con --no-sandbox (lib/research.py:72)."
  - "Allowlist de filesystem: incompleta. El scaffold de devops acepta cualquier target y solo hace resolve (lib/scaffold_devops.py:77), el portfolio acepta out_dir libre (mcp/handlers/portfolio.py:44) y apex_wiki_add concatena el slug sin sanitizar (mcp/handlers/wiki.py:33). Ver F5-05."
  - "Sin circuit breaker: no hay reintentos con cooldown ni estado half-open en ninguna ruta de red. Ver F5-04."
---

# L5 — Execution

Protege: ejecucion de codigo, llamadas a servicios externos. Cubre
ASI02, ASI03, ASI05.

Estado: **partial**. La revision de 2026-10-19 encontro dos afirmaciones
del informe de 2026-04-20 que ya NO eran ciertas ("cero outbound HTTP"
y "unico subprocess"): el sistema gano desde entonces cuatro rutas de red
y seis subprocess. El control de "no ejecutar codigo del usuario" sigue
siendo cierto. Quedan F5-01 a F5-05.

## Checklist

- [x] **No code execution**: cero `eval()`, `exec()` y `compile()` en
      `lib/` y `mcp/` (los `compile` presentes son `re.compile`). Verificado
      con grep.
- [ ] **No outbound HTTP**: FALSO desde 2026-04-20. Hay cuatro rutas de
      red: Ollama en localhost (lib/embeddings.py:44-60), httpx contra
      URLs arbitrarias (lib/research.py:53-65), urllib contra repos
      externos (lib/library_ingest.py:34-36) y Chrome headless
      (lib/browser_trace.py:176-212). No hay allowlist de hosts ni guard
      de DNS rebinding. Ver F5-03.
- [ ] **Subprocess allowlist**: ya no es unico. Ademas del hub, con
      binario y cwd fijos (mcp/apex_server.py:191-197), hay git
      (lib/grader.py:175-179, lib/reverse_engineer.py:79-85), chromium
      (lib/research.py:71-88), uvx (lib/library_ingest.py:444-457) y
      Chrome (lib/browser_trace.py:207-212). Ver F5-02.
- [ ] **Resource budgets**: no hay `resource.setrlimit` aplicado. No
      critico para el codigo del usuario (no lo ejecutamos), pero si para
      los ficheros de `raw/` que ingesta `apex_ingest_source` y para el
      DOM que descarga Chrome. Ver F5-01.
- [x] **Sandbox necesaria**: N/A para el codigo del usuario (no se
      ejecuta codigo generado). Nota: el Chromium que usa el research
      corre con `--no-sandbox` (lib/research.py:72), asi que esa ruta si
      queda fuera de un sandbox.
- [ ] **Allowlist filesystem**: incompleta. `.apex/` esta acotado en las
      escrituras normales, pero `apex_scaffold_devops`
      (lib/scaffold_devops.py:77), `apex_portfolio_draft`
      (mcp/handlers/portfolio.py:44) y `apex_wiki_add`
      (mcp/handlers/wiki.py:33) aceptan paths fuera del proyecto. Ver
      F5-03.
- [ ] **Circuit breaker**: no implementado, y ya es relevante: hay rutas
      de red que pueden fallar o colgarse. Ver F5-04.

## Findings abiertos

1. **F5-01 (baja)**: `resource.setrlimit(RLIMIT_AS, 512MB)` en el
   entrypoint de `apex_ingest_source` y limite de tamano de fichero, para
   proteger ante ficheros `raw/` de tamano extremo. Evidencia que lo
   cerraria: el limite aplicado y un test con un fichero gigante.
2. **F5-02 (baja)**: allowlist explicita de subprocess. Hoy conviven el
   hub, git, chromium, uvx y Chrome con binarios tomados del PATH
   (lib/research.py:77, lib/library_ingest.py:445-448). Evidencia que lo
   cerraria: tabla de binarios permitidos con su proposito, y test que
   compruebe que no se puede lanzar otro.
3. **F5-03 (media, NUEVO)**: allowlist de hosts de salida y guard de DNS
   rebinding. `apex_research_competitor` y `apex_browser_trace` alcanzan
   cualquier URL que le pase el caller (lib/research.py:53-65,
   lib/browser_trace.py:176-212). Evidencia que lo cerraria: resolucion
   previa del host contra una allowlist, con test que intente alcanzar
   `169.254.169.254`.
4. **F5-04 (media, NUEVO)**: circuit breaker con cooldown y estado
   half-open en las rutas de red, para que un Ollama caido no deje la
   sesion colgada. Evidencia que lo cerraria: el breaker con su test de
   N fallos y su reopening.
5. **F5-05 (media, NUEVO)**: validacion de paths en las tres tools que
   escriben fuera del proyecto (ver F4-02 en L4). El caso mas grave es
   `apex_wiki_add` (mcp/handlers/wiki.py:33), donde un slug con `..`
   escapa de `.apex/wiki`. Evidencia que lo cerraria: `resolve()` +
   `is_relative_to()` sobre la raiz permitida, con test de traversal.

## Verificacion reproducible (2026-10-19)

```bash
# Sin ejecucion de codigo
grep -rnE "(^|[^._a-zA-Z0-9])(eval|exec)\(" lib/ mcp/          # 0
# Outbound HTTP: ya NO es cero
grep -rnE "import (httpx|urllib.request|requests|aiohttp)" lib/    # 4 rutas
# Subprocess: ya NO es uno
grep -rn "subprocess" lib/ mcp/ --include=*.py
# Sin resource limits
grep -rn "setrlimit" lib/ mcp/                                  # 0
# Paths de escritura sin validar
sed -n '77p' lib/scaffold_devops.py
sed -n '44p' mcp/handlers/portfolio.py
sed -n '33p' mcp/handlers/wiki.py
```
