# Análisis — reescritura del router (commands/apex.md)

- **Fecha**: 2026-10-19
- **Autor**: análisis de la reescritura no fusionada de `commands/apex.md`
  (rama `origin/fix/cross-project-tone-2026-07-06`, commit `bce5bf6`)
- **Alcance**: SOLO análisis. No se ha implementado nada: no se ha tocado
  `commands/`, `skills/`, `lib/`, `mcp/`, `scripts/`, `tests/`, `.claude/` ni
  `.codex/`. Suite intacta: 1361 pasan, 5 omitidos, idéntica a `main`.

## Veredicto

La "reescritura" de la rama no es una reescritura: son **cinco bloques
añadidos** (+61/−12 líneas) sobre un router que **no ha cambiado desde el
2026-05-07**, así que portarla "tal cual" sería un error (arrastra dos
afirmaciones falsas sobre los gates, deja la mitad de las rutas en relativo
y cita dos skills que no existen), pero **tres de los cinco bloques —frontmatter,
resolución de la raíz del repo APEX y la sección de postura— son una mejora
real y hoy no existen en `main`**; el trabajo que hay que hacer no es "portar
la rama", es **actualizar el router**, que está caducado en las dos versiones.

---

## Las dos versiones

| | Actual (`main`) | Rama (`bce5bf6`) |
|---|---|---|
| Fichero | `commands/apex.md` | `commands/apex.md` |
| Líneas | 329 | 378 |
| Palabras | 2.005 | 2.407 |
| Último commit que lo toca | `193cdd7` (2026-05-07) | `bce5bf6` (2026-07-06) |
| Diff entre ambos | — | +61 / −12 líneas |

**El router de `main` está congelado desde el 2026-05-07.** El commit
`193cdd7 docs(s15.8-9)` es el último que toca `commands/apex.md` en `main`, y
es **anterior** al commit de la rama. Lo que ha evolucionado en estos cinco
meses no es el router: es la maquinaria que el router describe (`lib/`,
`mcp/`, `skills/`). Por eso la comparación relevante no es "versión vieja vs
versión nueva", sino "dos textos del 2026 contra un repo de 2026".

### Tabla de secciones

| Sección | Actual | Rama | Nota |
|---|---|---|---|
| Frontmatter YAML | no | sí (líneas 1-4) | `description` + `argument-hint` |
| PASO -1 — raíz del repo APEX | no | sí (13-28) | bloque nuevo |
| PASO CERO — `ToolSearch("apex")` | sí (10-64) | sí (30-83) | idéntico |
| Tabla de tools MCP | 38 filas | 38 filas | idéntica, y caduca en las dos |
| Detección del proyecto (A/B/C) | sí (67-141) | sí (87-160) | idéntico salvo la tabla de fases |
| Índice de las 14 fases + gate 10.5 | sí (144-171) | sí (164-189) | la rama sustituye el cierre normativo por un párrafo de enforcement |
| Roles especializados | sí (175-202) | sí (201-228) | idéntico |
| Apex-doctor | sí (206-230) | sí (232-256) | idéntico (y caduca en las dos) |
| Flujo Pocock | sí (234-296) | sí (260-321) | idéntico |
| Postura | no | sí (325-339) | bloque nuevo |
| Reglas transversales | sí (299-307) | sí (341-349) | 20 → 22 reglas, rutas con `$APEX_ROOT` |
| Arquitectura del comando | sí (311-327) | sí (353-376) | lista de skills ampliada |
| `$ARGUMENTS` | 329 | 378 | — |

Además, fuera del router, la rama **borró** `.claude/commands/apex.md`
(136 líneas). Ese fichero sigue vivo en `main` y es un comando `/apex`
**antiguo y distinto** (SMA de 5 fases, RAG contra ChromaDB en
`100.88.164.20:8000`). Al vivir en `.claude/commands/` del propio repo APEX,
**sombrea al comando de usuario** cuando se trabaja dentro del repo APEX.

---

## Bloque por bloque

| # | Bloque de la rama | Qué aporta | ¿Sigue siendo necesario? | ¿Choca con algo actual? | Recomendación |
|---|---|---|---|---|---|
| B1 | Frontmatter YAML (1-4) | `description` y `argument-hint`: el comando pasa a ser descubrible por descripción y admite un argumento. Los 25 `SKILL.md` ya llevan frontmatter (los 16 que faltaban se arreglaron el 2026-10-19); los comandos `templates/commands/*.md` también lo llevan | Sí, y es una asimetría: el router es el único artefacto de `/apex` sin frontmatter | No | **ADOPTAR** |
| B2 | PASO -1 — resolver la raíz del repo APEX (13-28) | Dice la verdad que faltaba: el comando vive en el repo APEX pero se ejecuta en el CWD del proyecto guiado, donde `commands/phases/*` no existe. Obliga a resolver `APEX_ROOT` y a leer en absoluto | **Sí, es un problema real y vigente** | Parcial: la resolución por `~/.claude/commands/apex.md` es específica de Claude Code y no coincide con la regla canónica de `skills/apex/SKILL.md:13-16` (tercer directorio padre del fichero de la skill) | **ADAPTAR** (no adoptar tal cual): validar la raíz contra un fichero marcador y no depender de un único symlink |
| B3 | "Criterio de cierre (vinculante)" (191-197) | Convierte en explícito lo que el gate hace: para cerrar, verdict del grader; el gate 10.5 bloquea la entrada en la 11; `force=True` + `force_reason` queda registrado | **A medias**: describe un enforcement que hoy es sólo parcial | **Sí, dos afirmaciones son falsas** (ver tabla de afirmaciones caducadas): el gate NO bloquea "si no hay verdict" salvo en 10.5, y el gate de "código antes de fase 5" no existe en `main` | **ADAPTAR**: reescribir el párrafo contra el código real, o **RECHAZAR** el párrafo y basta con el enforcement ya descrito en la tabla de fases (líneas 144-148) |
| B4 | Postura (325-339) | Traduce al orquestador las reglas 21-22. En `main` la postura existe, pero **sólo** en `commands/rules/absolute-rules.md:64-82` y en los subagentes (`lib/roles.py:460-471`); el router —que es lo que lee el orquestador— no la menciona, y el bloque APEX-AWARE del `CLAUDE.md` del proyecto tampoco (`lib/init_claude_md.py:159-181`) | Sí: es el único sitio donde la postura llega al orquestador sin que tenga que abrir el fichero de reglas | No | **ADOPTAR** |
| B5 | Reglas transversales con `$APEX_ROOT` y "22 reglas" (345-349) | Corrige el número de reglas (20 → 22) y hace que las rutas absolutas se apliquen también a las tres reglas | Sí: el "20 reglas" de `main` es falso desde que se añadieron la 21 y la 22 | No | **ADOPTAR** (la corrección del número, se haga o no el resto del port) |
| B6 | Lista de skills por fase (360-371) | Mapa skill→fase: información que no está en ninguna otra parte del repo y que el orquestador sí necesita | Sí, como mapa | **Sí**: de los 26 nombres, 2 no existen en `main` (`brain-to-docs`, `effective-agent-skills`) y omite `apex`, que es la skill de entrada de Codex/OpenCode | **ADAPTAR**: rehacer la lista sobre las 25 skills reales |
| B7 | Borrado de `.claude/commands/apex.md` (fuera del router) | Quita un comando `/apex` muerto que sombrea al router dentro del propio repo APEX | Sí | No | **ADOPTAR** (decisión de fichero aparte, no bloqueada por el resto del port) |

### Detalle de B2: el problema es real, la solución propuesta es frágil

Verificaciones:

- `~/.claude/commands/apex.md` es un **symlink** a
  `/home/vicente/RoadToDevOps/apex/commands/apex.md`. El comando se carga de
  ahí, pero el CWD del agente es el proyecto guiado: el propio router lo
  asume en `commands/apex.md:72` (`ls -la .apex/`) y `:87` (`git ls-files`),
  y el servidor MCP selecciona la BD por directorio de trabajo
  (`README.md:26-29`).
- Un proyecto guiado **no** recibe el router: `lib/scaffold_devops.py:109-129`
  copia a `<proyecto>/.claude/commands/` sólo los 4 comandos de
  `templates/commands/` (`apex-component`, `apex-decision`, `apex-error`,
  `apex-search`). No hay `commands/phases/` ni `skills/` en el proyecto.
- Por tanto las rutas relativas del router actual (`commands/apex.md:80`,
  `:100`, `:131`, `:137`, `:303-307`) **no resuelven** cuando el proyecto
  guiado no es el repo APEX. B2 acierta el diagnóstico.

Pero la implementación propuesta tiene un fallo silencioso: el comando de
resolución no valida nada.

```
$ readlink -f ~/.claude/commands/apex.md | xargs dirname | xargs dirname
/home/vicente/RoadToDevOps/apex          # con el symlink: correcto

$ readlink -f ~/.claude/commands/inexistente.md | xargs dirname | xargs dirname
/home/vicente/.claude                     # sin el symlink: raíz WRONG, sin error
```

Si el symlink no está (instalación por copia, otra máquina, otro entorno), el
router sigue "resuelto" y apunta a `~/.claude`, que no tiene `commands/phases/`.
La lectura siguiente falla con un error de fichero, no con un error de raíz.

Además la rama declara la regla de rutas absolutas (líneas 24-26) pero **no la
aplica**: el cuerpo sigue con rutas relativas en 100, 120, 151 y 157, y la
tabla de fases (170-187) usa `phases/00-socratic.md`. Un fichero que dice
"toda lectura usa ruta absoluta" y acto seguido lee en relativo no es un
router fiable: el agente cumple una regla u otra según cómo lo lea.

Lo que hay hoy para resolver la raíz, y que la rama no menciona:

- `skills/apex/SKILL.md:13-16`: "Resuelve la ruta real del archivo (puede
  estar instalado mediante un enlace simbólico) y toma su tercer directorio
  padre como `APEX_ROOT`". Es la regla canónica, y funciona en Codex y
  OpenCode (donde no existe `~/.claude/commands/`).
- `.opencode/commands/apex.md:7`: "Resuelve `APEX_ROOT` desde la ruta real de
  la skill; no uses como raíz la ruta del enlace `~/.agents/skills/apex`".
- `lib/project_root.py:99-145`: `find_project_root`, `resolve_project_root`,
  `project_db_path`. **Ojo**: esto resuelve la raíz del *proyecto* (dónde está
  `.apex/context.db`), **no** la raíz del *repo APEX*. No sirve para B2 y no
  hay que confundir las dos cosas: hoy no existe ninguna función que resuelva
  la raíz del repo APEX en el repo, y por eso B2 hace falta.

---

## Lo que la versión de la rama perdería

La rama borra 12 líneas de la actual. Ninguna es una pérdida de fondo, pero una
sí es una pérdida real:

| Línea actual | Qué se pierde | Gravedad |
|---|---|---|
| `commands/apex.md:170-171` — "Nunca declarar una fase como `completed` sin TODOS sus sub-pasos verificados" | La rama lo sustituye por un párrafo sobre el **verdict del grader** (191-197). El requisito de sub-pasos (que es la regla absoluta 7, `commands/rules/absolute-rules.md:27`) no es lo mismo que el verdict: un verdict favorable sin sub-pasos hechos sigue siendo un cierre en falso | **Pérdida real**: es la única norma del router que no depende del grader |
| `commands/apex.md:8` — "Reglas transversales en `commands/rules/`." | Sustituida por la versión con `$APEX_ROOT` (28). No es pérdida | Ninguna |
| `commands/apex.md:303-307` — "20 reglas absolutas" y las dos rutas siguientes | Sustituidas por la versión con `$APEX_ROOT` y "22" (345-349). Corrección, no pérdida | Ninguna |
| `commands/apex.md:318-322` — lista de 16 skills | Sustituida por el mapa de 26 (360-371). Amplía, no pierde | Ninguna |

Y hay dos pérdidas **fuera del texto**, que son las importantes:

1. **El cierre "a ojo" no está del todo cerrado.** El párrafo de la rama
   (191-197) promete "el cierre 'a ojo' no existe". En `main` es verdad a
   medias: `mcp/handlers/context.py:133-141` sólo bloquea si hay verdict y
   `should_block`, y sólo es *fail-closed* (sin verdict = bloquea) para la
   fase 10.5 (`mcp/handlers/context.py:47` y `:135-137`). Para las demás fases, cerrar sin
   verdict **pasa**. La tabla de fases del router actual (líneas 144-148) es
   más honesta que el párrafo de la rama en este punto.
2. **El router de la rama no menciona la maquinaria nueva**: ni el gate 10.5
   fail-closed, ni la regla 18 con maquinaria (`lib/cross_project_flag.py:26`,
   `lib/grader.py:38,288,301`), ni las tools del VFS, ni la biblioteca de
   libros, ni el curador. Pero **eso tampoco lo menciona el router actual**:
   no es una regresión del port, es deuda común.

### Lo que ambas versiones tienen caducado (no viene de la rama)

| Afirmación común | Realidad verificada |
|---|---|
| "Lista completa" de tools MCP (38 filas) | Hay **64** tools registradas (`mcp/apex_server.py`, 64 nombres `apex_*`). Faltan 27 en la tabla: las 4 del VFS, las 3 de la biblioteca, las 2 del curador, las 4 del advisor, las 3 del skill-forge, `apex_prototype_init`, `apex_handoff_skill`, `apex_resume_skill_handoff`, `apex_dismiss_advice`, `apex_phase_entry_check`, `apex_db_compact`, `apex_browser_trace`, `apex_log_trace`, `apex_record_advice`, `apex_rate_advice`, `apex_ingest_library_skills` |
| `apex_security_gate` aparece **dos veces** en la tabla (rama 63 y 80; actual 43 y 60) | Duplicado en las dos |
| "Apex-doctor: 3 analizadores" (rama 79 y 246; actual 59 y 220) | Son **6**: A1-A6 (`lib/apex_doctor.py:9-33`, funciones en 179, 238, 313, 498, 588, 701) |
| "5 roles agente" / "`apex_install_roles()` escribe los 5 archivos" (actual 177, 193) | **6** roles: `ROLES` incluye `apex-advisor` (`lib/roles.py:340-435`) |
| "`apex_recommend_role(phase=N)` devuelve None para fases 0, 1, 10.5, 12" (actual 196) | `PHASE_ROLE_MAP` (`lib/roles.py:38-49`) no define 0, 1, 10.5, 12 **ni 13 ni 14** |

---

## Afirmaciones caducadas

| Afirmación en la rama | ¿Sigue siendo cierta? | Evidencia |
|---|---|---|
| "Este comando vive en el repo APEX, pero se ejecuta en el CWD del proyecto guiado (que NO contiene `commands/phases/*` ni `skills/*`)" (15-16) | **Sí** | `~/.claude/commands/apex.md` es symlink al repo; el CWD es el proyecto (`commands/apex.md:72,87`; `README.md:26-29`); el proyecto guiado sólo recibe 4 comandos de `templates/commands/` (`lib/scaffold_devops.py:109-129`) |
| "APEX_ROOT se resuelve con `readlink -f ~/.claude/commands/apex.md \| xargs dirname \| xargs dirname`" (20) | **Sí en esta máquina, frágil en general** | Devuelve `/home/vicente/RoadToDevOps/apex`; sin el symlink devuelve `/home/vicente/.claude` en silencio (probado) |
| "Las rutas relativas (`commands/phases/...`) NO resuelven fuera del repo APEX" (26) | **Sí** | Verificado: el proyecto guiado no recibe `commands/phases/` |
| "A partir de aquí, TODA lectura usa ruta absoluta" (24) | **No: el propio fichero no lo cumple** | Rutas relativas en 100, 120, 151, 157 y en la tabla de fases (170-187) |
| "Un gate (hook `phase-gate.py`) rechaza `apex_set_phase(..., completed)` si no hay verdict o si el verdict bloquea" (193-194) | **FALSA en la primera mitad** | `.claude/hooks/phase-gate.py:245`: `if not verdict or not verdict["should_block"]: continue` — sin verdict no bloquea. El handler tampoco: `mcp/handlers/context.py:135-137` sólo marca bloqueo sin verdict para `_FASES_FAIL_CLOSED = {GATE_PHASE}` (`mcp/handlers/context.py:47`) |
| "un gate rechaza escribir código de producción antes de fase 5" (195-196) | **FALSA: ese gate no existe en `main`** | `AGENTS.md:182-186`: "no existe como código. Sólo quedan dos `.pyc` huérfanos"; `grep -rn "code-before-phase5"` sólo encuentra AGENTS.md y la deuda de 2026-07-21. Vivió sólo en `bce5bf6` |
| "otro rechaza entrar a fase 11 sin las capas de seguridad L1-L8 en `passed`" (196) | **Sí, en efecto** | `lib/security_gate.py:82-83,155-191` traduce el estado de las capas a `should_block`; `apex_security_gate` escribe ese verdict (`mcp/handlers/security.py:37`); el handler es fail-closed para 10.5 (`mcp/handlers/context.py:47,135-137`) |
| "Todos aceptan `force=True` con `force_reason` (queda registrado como error)" (196-197) | **Sí** | `mcp/handlers/context.py:184-204`: registra `apex_add_error` de severidad `high` por cada override |
| "para cerrar una fase debes llamar `apex_grader_evaluate(phase=N, ...)` y obtener un verdict NO bloqueante" (191-192) | **Parcialmente**: el *procedimiento* lo prescriben los ficheros de fase (`tests/test_phase_docs_coverage.py:38-46` lo verifica en las 16), pero el handler **no** lo exige: sin verdict, una fase normal cierra | `mcp/handlers/context.py:133-141` |
| "`absolute-rules.md` — 22 reglas absolutas (21-22 gobiernan la postura)" (345-346) | **Sí** | `commands/rules/absolute-rules.md`: 22 reglas numeradas; la 21 (línea 64) y la 22 (línea 78) son la postura |
| "Los 26 tienen frontmatter con `description`" (360-362) | **FALSA en el número y en 2 nombres** | Hay **25** skills y las 25 tienen frontmatter. `brain-to-docs` y `effective-agent-skills` (nombres citados en 362-371) **no existen** en `main`: el `git ls-tree` de `bce5bf6` los tiene, `main` no. La lista omite `apex`, la skill de entrada de Codex/OpenCode |
| "Apex-doctor: 3 analizadores" (79 y 246) | **FALSA** | `lib/apex_doctor.py:9-33`: A1-A6 |
| "5 roles agente" / "escribe los 5 archivos" | **FALSA** | `lib/roles.py:340-435`: 6 roles (incluido `apex-advisor`) |
| "None para fases 0, 1, 10.5, 12" (196 actual / equivalente en la rama) | **Incompleta** | `lib/roles.py:38-49`: tampoco hay rol para 13 y 14 |
| "Lista completa" de tools MCP | **Incompleta: 37 únicas de 64** | Las 37 listadas existen todas; faltan 27 |
| "Un gate bloquea escribir código antes de fase 5" | **FALSA** | Es la misma afirmación de la fila del gate de fase 5, repetida en el cuerpo (195-196). El frontmatter (línea 2) dice "gates de fase y de seguridad", que sí existen: el problema es el cuerpo, no la descripción |

---

## Veredicto y plan

### Qué se porta

| Orden | Qué | Cómo | Riesgo |
|---|---|---|---|
| 1 | **Frontmatter YAML** (B1) | Copiar las 4 líneas de la rama | Nulo. `tests/test_pocock_wiring.py` no lo toca |
| 2 | **Borrar `.claude/commands/apex.md`** (B7) | `git rm` del fichero muerto | Bajo, y va en su propio commit: hoy `/apex` dentro del repo APEX ejecuta el comando SMA antiguo en vez del router |
| 3 | **Sección Postura** (B4) | Copiar 325-339, adaptando la redacción a las reglas 21-22 tal como están hoy (`commands/rules/absolute-rules.md:64-82`) | Nulo. Es texto normativo, no código |
| 4 | **"22 reglas absolutas"** (B5) | Cambiar el 20 por el 22 en `commands/apex.md:303` | Nulo |
| 5 | **PASO -1 — resolución de la raíz** (B2) | **Adaptado, no copiado**: (a) validar `APEX_ROOT` contra un fichero marcador (`[ -f "$APEX_ROOT/commands/phases/00-socratic.md" ]`) y fallar ruidosamente si no; (b) no depender sólo de `~/.claude/commands/apex.md`: aceptar también la ruta de la skill (`~/.agents/skills/apex/SKILL.md`, tercer directorio padre, la regla de `skills/apex/SKILL.md:13-16`); (c) aplicar la ruta absoluta **en todas** las referencias (100, 120, 151, 157 y la tabla 170-187), no sólo declararla | Medio: es la parte que cambia el comportamiento del router. Por eso va sola, con un test que verifique que no queda ninguna ruta relativa |
| 6 | **Mapa de skills por fase** (B6) | Rehacerlo sobre las 25 skills reales, con `apex` incluida y sin las 2 inexistentes | Bajo |

### Qué no se porta nunca

- El **párrafo "Criterio de cierre (vinculante)"** (rama 191-197) tal cual:
  afirma un gate de "código antes de fase 5" que no existe y un bloqueo "si no
  hay verdict" que no es cierto salvo en 10.5. Si se quiere el énfasis en el
  enforcement, se reescribe contra `mcp/handlers/context.py:119-220` y
  `.claude/hooks/phase-gate.py`, con las frases exactas del código.
- Las **skills `brain-to-docs` y `effective-agent-skills`**: son contenido
  externo (github.com/davidondrej/skills) que se decidió no traer
  (`AGENTS.md:194`). Portar el nombre sin el fichero deja la lista mintiendo.
- La **tabla de tools tal cual**: si se toca, se regenera contra las 64
  registrations reales, no se parchea.

### Qué haría falta para que el port sea seguro

1. **Un test de contrato del router**, del estilo de
   `tests/test_pocock_wiring.py:28-49`: que verifique que no queda ninguna
   ruta relativa a `commands/` o `skills/` fuera de las que deben ser
   relativas, y que `APEX_ROOT` se valida contra un marcador. Sin ese test,
   el paso 5 es una edición de markdown sin red.
2. **Decidir el mecanismo único de resolución de la raíz** y dejarlo escrito
   en un solo sitio, o el router y `skills/apex/SKILL.md:13-16` acabarán
   divergiendo otra vez. Hoy conviven dos reglas (symlink de Claude Code vs
   tercer directorio padre de la skill) y la rama añade una tercera.
3. **Actualizar el resto del router**, que es deuda común y no viene de la
   rama: la tabla de tools (37 de 64), "3 analizadores" (son 6), "5 roles"
   (son 6), los `None` de `apex_recommend_role` (también 13 y 14), y el
   duplicado de `apex_security_gate`.
4. **Añadir al router la maquinaria que hoy no menciona**: gate 10.5
   fail-closed, la regla 18 con maquinaria
   (`lib/cross_project_flag.py:26`, `lib/grader.py:38,288,301`), las tools
   del VFS y la biblioteca. Sin esto, el router sigue siendo un documento de
   2026 sobre un repo de 2026.

### Lo que NO se pierde por no portar

Nada de lo que la rama añade es irrecuperable: el commit sigue en
`origin/fix/cross-project-tone-2026-07-06` y `git show bce5bf6:commands/apex.md`
lo devuelve. Portar por partes no obliga a decidir nada irreversible.

---

## Qué se comprobó

- Lectura íntegra de las dos versiones (`commands/apex.md`, 329 líneas;
  `git show bce5bf6:commands/apex.md`, 378 líneas) y `diff -u` completo:
  +61/−12 líneas, 5 bloques.
- `git log` de `commands/apex.md` en ambas ramas: el router de `main` no
  cambia desde `193cdd7` (2026-05-07).
- Tools MCP: 64 nombres `apex_*` extraídos de `mcp/apex_server.py`; las 37
  listadas por la rama existen; 27 no listadas.
- Gates: `.claude/hooks/phase-gate.py:245`, `.codex/hooks/phase-gate.py:245`,
  `mcp/handlers/context.py:47,119-220`, `mcp/handlers/security.py:37`,
  `lib/security_gate.py:82-83,155-191`.
- Reglas: `commands/rules/absolute-rules.md` (22 numeradas; 21 en línea 64,
  22 en línea 78).
- Roles: `lib/roles.py:38-49,340-435` → 6 roles, mapa de fases sin 13/14.
- Doctor: `lib/apex_doctor.py:9-33` → 6 analizadores.
- Skills: 25 directorios en `skills/`, las 25 con frontmatter;
  `git ls-tree bce5bf6 skills/` → 26 (con `brain-to-docs` y
  `effective-agent-skills`).
- Resolución de la raíz: `~/.claude/commands/apex.md` (symlink verificado),
  `readlink -f` con y sin symlink (comportamiento silencioso verificado),
  `lib/project_root.py:99-145` (resuelve el proyecto, **no** el repo APEX),
  `skills/apex/SKILL.md:13-16`, `.opencode/commands/apex.md:7`,
  `lib/scaffold_devops.py:109-129` + `templates/commands/`.
- Enrutado por entorno: `README.md:7-58`, `.claude/settings.json` y
  `~/.claude/settings.json` (el `phase-gate.py` está registrado a nivel
  global de Claude Code, no en el `settings.json` del proyecto).
- Suite: `PYTHONPATH=lib .venv/bin/pytest tests/ -q` → **1361 pasan, 5
  omitidos**, idéntica a `main`. No se ha tocado ningún fichero de código.
