# APEX — métricas para el paper ASE 2026 (Tools & Datasets)

> Generado con `scripts/paper_metrics.py` el 2026-05-10 (repo en `ddbe6b1`).
> Reproducible: `cd ~/RoadToDevOps/apex && .venv/bin/python3 scripts/paper_metrics.py [--json]`

## Tamaño del artefacto (lo que entra en el repo `apex-harness`)

| Métrica | Valor |
|---|---|
| Tests pasando (pytest) | **620** |
| Tools MCP expuestas | **53** |
| Skills (`SKILL.md`) | **24** |
| Hooks (SessionStart / PreToolUse / PostToolUse / UserPromptSubmit) | **11** |
| LOC Python en `lib/` | **~12 280** en 32 módulos |
| Tablas en `context.db` (sin contar índices FTS5) | **25** |
| Commits | **68** |

## Uso en campo (datos reales, no sintéticos)

APEX se ha usado como harness de trabajo en **24 proyectos** con `.apex/context.db`;
**20** de ellos con actividad sostenida (≥5 decisiones o ≥5 páginas wiki registradas).
Agregados cross-project en `apex-hub/data/hub.db`:

| Métrica | Total cross-project |
|---|---|
| Proyectos registrados en el hub | **24** |
| Decisiones registradas | **322** |
| Errores registrados (memoria bidireccional con `recurrence_count`) | **184** |
| Componentes | **279** |
| Páginas wiki | **160** |
| Live events (telemetría hub) | **282** |
| Session logs | **65** |

Dominios de los 20 proyectos reales: webs (`vr-web`, `corporate-web`, `frontend-zyndra`,
`vicente-portfolio-system`), sistemas multi-agente (`etibotti`, `sma-supermercados`,
`clase-agentes`), tooling académico / TFGs (`TFG-Tutor-Virtual`, `v2-tutor-virtual`,
`tesis-telecom`, `herramienta-correccion`, `feedback-juanmi`), tooling de investigación
(`baul-ideas`, `auditoria-osyris`, `server-audit`), planificación (`planificadorIA`,
`meridian`, `lo-minimo`), productividad (`FocusNow`), y el propio dogfooding de APEX
(`apex`, `apex-hub`).

## Maquinaria de auto-mejora — estado honesto

Implementada y cubierta por tests unitarios, **uso en producción casi nulo todavía**
(se construyó en los sprints 8–15; aún no batalla-probada a escala):

| Mecanismo | Verdicts/cards/registros en campo |
|---|---|
| Grader (juicio outcome-based) | 1 verdict |
| Advisor (subagent Opus, cards) | 0 cards / 0 reviews registradas en context.db |
| apex-doctor (analizadores de intención) | 3 propuestas |
| Reasoning traces (Hermes-style) | 1 traza |
| Role invocations (5 subagents) | 0 |
| Skill handoffs intra-sesión | 0 |

→ En el paper: describir grader/advisor/doctor/skill-forge como **mecanismos
implementados y unit-tested**, no reclamar impacto empírico. Es "future work".
La evidencia de utilidad real = (a) 620 tests, (b) 20 proyectos reales durante ~2 meses,
(c) 322 decisiones + 184 errores + 160 wiki pages de trabajo real agregados en el hub,
(d) ejemplos concretos de errores atrapados (abajo).

## Ejemplos concretos de errores atrapados / inyectados como guardrails cross-project

De `hub.db` (lecciones que `session-start.py` inyecta al arrancar cualquier proyecto APEX):

1. **FocusNow**: propuso stack SwiftUI sin ejecutar `uname -s` primero → invalidado
   al resultar el SO ser Linux. → Lección inyectada: "ejecutar `uname -s` antes de
   proponer stack dependiente de plataforma".
2. **FocusNow**: usó emojis como iconos de UI. → Lección: "nunca emojis; SVG/Lucide".
3. **FocusNow**: declaró fases de integración/frontend completas con datos mock
   hardcodeados, sin conectar al backend real. → Lección: "no declarar fase
   integración/frontend completa con mocks; verificar E2E contra backend real".
4. **FocusNow**: no se inicializó git ni hubo commits en fases 5–11; todo el código
   sin versionar. → Lección: "git init + primer commit como primer sub-paso de fase 5".
5. **tfg-tutor-virtual**: las concepciones alternativas detectadas por el classifier
   agent no se propagaban al tutor agent. → Lección: "en orquestaciones, los datos
   detectados upstream deben fluir explícitamente en el `context` compartido".

Estos cinco son `critical` en `hub.db.errors` y se reinyectan en cada `SessionStart`.

## Cosas a NO afirmar en el paper

- "Los 20 proyectos llegaron a la fase 14" — FALSO. La tabla `phases` se prepuebla con
  las 15 filas (0–14) en el `init`; `MAX(phase)` no indica progreso real.
- Cualquier número de efectividad del grader/advisor — no hay datos.
- "Reduce X% de errores" — no medido.
