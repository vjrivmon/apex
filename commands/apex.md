# /apex — Sistema de desarrollo guiado por fases

Router. Cada fase vive en su propio archivo bajo `commands/phases/`. Este
comando NO contiene la logica de cada fase — la carga bajo demanda
(progressive disclosure) leyendo solo el archivo que corresponde al estado
actual del proyecto.

Reglas transversales en `commands/rules/`.

## PASO CERO — Cargar herramientas MCP

Este comando REQUIERE las herramientas MCP de APEX. Ejecuta SIEMPRE al
inicio:

```
ToolSearch("apex")
```

Las herramientas se llaman `mcp__apex__apex_*`. Lista completa:

| Tool                                     | Uso                                      |
| ---------------------------------------- | ---------------------------------------- |
| `mcp__apex__apex_init_project`           | Crear `.apex/` al inicio                 |
| `mcp__apex__apex_get_context`            | Leer estado del proyecto (compact/timeline/full) |
| `mcp__apex__apex_set_phase`              | Cambiar de fase                          |
| `mcp__apex__apex_add_decision`           | Registrar cada decision                  |
| `mcp__apex__apex_add_error`              | Registrar errores                        |
| `mcp__apex__apex_add_component`          | Registrar componentes                    |
| `mcp__apex__apex_add_next_step`          | Proximos pasos                           |
| `mcp__apex__apex_complete_step`          | Marcar paso completado                   |
| `mcp__apex__apex_search`                 | Buscar en contexto (fts/hybrid)          |
| `mcp__apex__apex_search_cross_project`   | Buscar en hub agregado                   |
| `mcp__apex__apex_log_session`            | Registrar sesion                         |
| `mcp__apex__apex_wiki_add`               | Anadir al knowledge base                 |
| `mcp__apex__apex_invalidate_decision`    | Invalidar decision anterior              |
| `mcp__apex__apex_update_component`       | Actualizar componente existente          |
| `mcp__apex__apex_set_portfolio_meta`     | Campos portfolio para publicacion        |
| `mcp__apex__apex_portfolio_draft`        | Generar MDX para vr-web                  |
| `mcp__apex__apex_ingest_source`          | Pipeline 8-pasos de second brain         |
| `mcp__apex__apex_lint_second_brain`      | Linter auto-healing del wiki             |
| `mcp__apex__apex_synthesize`             | Promocion density-triggered              |
| `mcp__apex__apex_scaffold_devops`        | Templates CI/CD/Docker/observability     |
| `mcp__apex__apex_security_gate`          | Gate AgentArmor 8-capas (fase 10.5)      |

**Si `ToolSearch` no devuelve herramientas apex, avisa al usuario de que
debe reiniciar Claude Code con el MCP server de APEX activo.**

---

## Deteccion del proyecto

### Paso 1: Verificar estado

```bash
ls -la .apex/ 2>/dev/null && echo "APEX_EXISTS" || echo "APEX_NEW"
uname -s
```

Segun el resultado, seguir Caso A, Caso B o Caso C.

### Caso A — Proyecto nuevo (no existe `.apex/` NI codigo)

Ir directamente a **Fase 0**: leer `commands/phases/00-socratic.md`.

### Caso B — Proyecto existente SIN `.apex/` (tiene codigo/git pero no APEX)

Decision branch segun tamaño del repositorio:

```bash
FILES=$(git ls-files 2>/dev/null | wc -l)
if [ "$FILES" -gt 50 ]; then
  echo "LARGE_PROJECT — usar /apex:reverse"
else
  echo "SMALL_PROJECT — onboarding superficial"
fi
```

#### B.1 — Proyecto grande (>50 archivos tracked): `/apex:reverse`

REGLA ABSOLUTA: el CODIGO manda sobre README/CLAUDE.md. Esos archivos
suelen estar desactualizados.

Leer `commands/apex-reverse.md` y seguir el flujo completo:
SCAN → REVIEW → BRAINSTORM → ASK → PLAN → APPROVE → APPLY → ITERATE.

El scanner `apex_reverse_scan` escanea el codigo real con git+glob+grep,
NO los docs, y emite findings retroactivos mapeados a cada una de las
14 fases + gate 10.5.

#### B.2 — Proyecto pequeño (<50 archivos): onboarding superficial

Invocar skill `onboard-existing`. Pasos breves:

1. Ejecutar:
   ```bash
   git log --oneline -20 2>/dev/null
   ls -la
   cat package.json 2>/dev/null || cat pyproject.toml 2>/dev/null || cat requirements.txt 2>/dev/null
   ls -la tests/ test/ __tests__/ spec/ 2>/dev/null
   ```
2. Detectar fases ya hechas:
   - Entidades de dominio / modelos → Fase 6 parcial o completa
   - Tests → Fase 9 parcial
   - Dockerfile / CI → Fase 11 parcial
   - BD configurada → Fase 7 parcial
   - Endpoints / routes → Fase 8 parcial
3. Llamar a `apex_init_project` con la info detectada.
4. Marcar fases detectadas como `completed` o `partial` con
   `apex_set_phase`.
5. Registrar cada hallazgo con
   `apex_add_decision(category="detected", ...)`.
6. Presentar resumen: "He detectado X, Y, Z. Faltan A, B, C."
7. Proponer continuar desde la primera fase incompleta leyendo
   `commands/phases/NN-*.md` correspondiente.

### Caso C — Proyecto con `.apex/` (continuacion)

1. `mcp__apex__apex_get_context(level="timeline")`.
2. Leer fase actual y sub-paso pendiente.
3. Leer `commands/phases/NN-*.md` correspondiente a la fase actual.
4. Continuar desde donde se quedo — NO preguntar "que quieres hacer", ir
   directo al siguiente sub-paso pendiente.
5. Si el usuario tiene una peticion especifica, atenderla y registrarla.

---

## Las 14 fases + gate 10.5 (indice)

14 fases secuenciales (0→14) con un gate obligatorio 10.5 entre las fases
10 y 11 que bloquea el deploy si la auditoria AgentArmor no esta passed.
El gate NO es una fase nueva, es un checkpoint entre fases 10 y 11.

| Fase | Archivo                              | Resumen                                                              |
| ---- | ------------------------------------ | -------------------------------------------------------------------- |
| 0    | `phases/00-socratic.md`              | Escuchar, investigar mercado, cuestionar (4 rondas + reflexion)      |
| 1    | `phases/01-solution-type.md`         | CLI / bot / MCP / app / agente (evaluar SO)                          |
| 2    | `phases/02-design.md`                | C4 + design system multi-tool + wireframes + flows                   |
| 3    | `phases/03-spec.md`                  | Reflexion + modelo de datos + checkpoints deployables                |
| 4    | `phases/04-edge-cases.md`            | ANTES del codigo, TODOS los posibles, sin limite                     |
| 5    | `phases/05-scaffold.md`              | Estructura hexagonal + config + verificar que compila                |
| 6    | `phases/06-core.md`                  | Domain + ports + casos de uso + agentes SMA                          |
| 7    | `phases/07-infrastructure.md`        | BD + LLM + scraping + adapters                                       |
| 8    | `phases/08-integration.md`           | Conectar todo, Streamlit para validar                                |
| 9    | `phases/09-testing.md`               | Unit 80% + integration + E2E Playwright + edge cases + coverage      |
| 10   | `phases/10-security.md`              | Validation + auth + headers + rate limit + audit                     |
| 10.5 | `phases/10.5-agentarmor-gate.md`     | **GATE bloqueante**: 8 capas AgentArmor passed antes de fase 11      |
| 11   | `phases/11-deploy.md`                | Docker + CI/CD + health + rollback + SSL + go-live                   |
| 12   | `phases/12-iteration.md`             | Features / bugs / mejoras (fase viva, siempre `in_progress`)         |
| 13   | `phases/13-scaling.md`               | Profiling + caching + monitoring + dashboard                         |
| 14   | `phases/14-maintenance.md`           | CI/CD + backups + docs auto + migraciones + plan deprecacion         |

Cada fase tiene sub-pasos SECUENCIALES y OBLIGATORIOS ejecutados EN ORDEN.
Nunca declarar una fase como `completed` sin TODOS sus sub-pasos
verificados.

---

## Reglas transversales

Antes de cualquier fase, tener leidas en contexto:

- `commands/rules/absolute-rules.md` — 20 reglas absolutas. Violar = fase
  falla.
- `commands/rules/errors-to-avoid.md` — Errores documentados
  cross-project.
- `commands/rules/ux-verification.md` — Playwright + `/apex:idea` flow.

---

## Arquitectura del comando

- **Router (`apex.md`)** = orquestador. Detecta fase, carga fase,
  delega.
- **Fases (`phases/*.md`)** = dominio. Cada fase es un modulo aislado con
  sub-pasos y criterio de salida.
- **Reglas (`rules/*.md`)** = invariantes. Se cumplen en todas las fases.
- **Skills (`skills/*/SKILL.md`)** = agentes especializados invocados
  segun contexto (socratic, architect, brand-identity, second-brain,
  devops, security-audit, code-review, flow-guardian, iterate, monitor,
  onboard-existing, portfolio-publisher, design-research, design-system,
  tools-integration).
- **MCP tools (`mcp__apex__*`)** = adapters al context.db + hub.

Aplicacion directa del principio hexagonal + SMA: orquestador delega,
cada modulo encapsula una responsabilidad, los limites estan en los
`rules`.

$ARGUMENTS
