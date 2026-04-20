# APEX — Fases (progressive disclosure)

Cada fase vive en su propio archivo. El router (`commands/apex.md`) solo
carga la fase actual mediante Read cuando Claude Code la necesita. Esto
evita inflar el contexto con 600+ lineas innecesarias y respeta el patron
Anthropic de progressive disclosure.

## Indice

| Fase | Archivo                              | Resumen                                                              |
| ---- | ------------------------------------ | -------------------------------------------------------------------- |
| 0    | `00-socratic.md`                     | Escuchar, investigar mercado, cuestionar (4 rondas + reflexion)      |
| 1    | `01-solution-type.md`                | CLI / bot / MCP / app / agente (evaluar SO)                          |
| 2    | `02-design.md`                       | C4 + design system multi-tool + wireframes + flows                   |
| 3    | `03-spec.md`                         | Reflexion + modelo de datos + checkpoints deployables                |
| 4    | `04-edge-cases.md`                   | ANTES del codigo, TODOS los posibles, sin limite                     |
| 5    | `05-scaffold.md`                     | Estructura hexagonal + config + verificar que compila                |
| 6    | `06-core.md`                         | Domain + ports + casos de uso + agentes SMA                          |
| 7    | `07-infrastructure.md`               | BD + LLM + scraping + adapters                                       |
| 8    | `08-integration.md`                  | Conectar todo, Streamlit para validar                                |
| 9    | `09-testing.md`                      | Unit 80% + integration + E2E Playwright + edge cases + coverage      |
| 10   | `10-security.md`                     | Validation + auth + headers + rate limit + audit                     |
| 10.5 | `10.5-agentarmor-gate.md`            | **GATE bloqueante**: 8 capas AgentArmor passed antes de fase 11      |
| 11   | `11-deploy.md`                       | Docker + CI/CD + health + rollback + SSL + go-live                   |
| 12   | `12-iteration.md`                    | Features / bugs / mejoras (fase viva, siempre `in_progress`)         |
| 13   | `13-scaling.md`                      | Profiling + caching + monitoring + dashboard                         |
| 14   | `14-maintenance.md`                  | CI/CD + backups + docs auto + migraciones + plan deprecacion         |

## Como se usan

1. El router `commands/apex.md` detecta la fase actual via
   `apex_get_context(level="compact")`.
2. Lee SOLO el archivo de la fase actual: `commands/phases/NN-*.md`.
3. Ejecuta los sub-pasos `[Na] → [Nb] → ...` en orden.
4. Al cerrar, verifica criterio de salida y marca
   `apex_set_phase(status="completed")`.
5. Si la siguiente fase requiere gate (ej. 10 → 10.5 → 11), respeta el
   bloqueante.

## Reglas cross-fase

Ver `commands/rules/absolute-rules.md`, `commands/rules/errors-to-avoid.md`
y `commands/rules/ux-verification.md`.
