"""Sprint 12 — Virtual office: 5 roles agentes especializados.

APEX no ejecuta los roles directamente: declara los agentes y prepara los
prompts de invocación. La ejecución la hace Claude Code (orquestador main)
disparando el `Task` tool con `subagent_type="apex-<role>"`. Este módulo:

1. Define el registro `ROLES` con 5 specs (architect, implementer, reviewer,
   qa, devops). Cada spec contiene: nombre, descripción, tools permitidas,
   modelo, color, fases recomendadas y plantilla de system prompt.
2. Instala los archivos `~/.claude/agents/apex-<role>.md` con el frontmatter
   YAML que Claude Code consume para registrar subagents.
3. Construye el prompt de invocación a partir de un contexto de fase.
4. Registra cada invocación en `role_invocations` (context.db) para
   telemetría cross-sprint.

Diseño:

- `RoleSpec` es un dataclass inmutable; los campos `tools` son una lista de
  glob patterns que respeta el formato del frontmatter de Claude Code (e.g.
  "Read", "mcp__apex__*").
- Las plantillas usan placeholders `{phase}`, `{phase_name}`, `{context}`,
  `{project_name}`. Si falta alguno, se sustituye por "(sin dato)".
- `install_role` es idempotente: si el archivo destino existe y `force=False`,
  no lo toca. `force=True` reescribe.
- `record_invocation` y `get_invocations` usan sqlite3 síncrono porque los
  consumen tanto el MCP server (asyncio loop) como hooks (no asyncio).
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ── Mapping fase → rol ────────────────────────────────────────────────────

PHASE_ROLE_MAP: dict[int, str] = {
    2: "apex-architect",
    3: "apex-architect",
    4: "apex-qa",
    5: "apex-implementer",
    6: "apex-implementer",
    7: "apex-implementer",
    8: "apex-reviewer",
    9: "apex-qa",
    10: "apex-reviewer",
    11: "apex-devops",
}

PHASE_NAMES: dict[int, str] = {
    0: "socrático", 1: "tipo de solución", 2: "diseño", 3: "spec",
    4: "edge cases", 5: "scaffold", 6: "core", 7: "infraestructura",
    8: "integración", 9: "testing", 10: "seguridad",
    11: "deploy", 12: "iteración", 13: "scaling", 14: "mantenimiento",
}


# ── RoleSpec ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RoleSpec:
    """Especificación de un rol agente."""
    name: str                                # apex-architect
    description: str                         # 1-2 sentence + 2 examples
    tools: tuple[str, ...]                   # whitelist de tools/glob patterns
    model: str = "sonnet"                    # haiku | sonnet | opus | inherit
    color: str = "blue"                      # cosmético en la UI
    system_prompt: str = ""                  # cuerpo markdown del agent.md
    phases: tuple[int, ...] = ()             # fases en las que se recomienda


# ── Plantillas de system prompt ──────────────────────────────────────────

_ARCHITECT_PROMPT = """\
Eres el **Architect** del sistema APEX. Tu responsabilidad es diseñar
arquitecturas y tomar decisiones de stack que sobrevivan al sprint actual y
a los siguientes.

## Cuándo intervienes

- Fase 2 (diseño): C4, design system multi-tool, wireframes, flows.
- Fase 3 (spec): modelo de datos, checkpoints deployables, decisiones de
  stack documentadas en `wiki/decisions/`.

## Reglas absolutas

1. **El código manda sobre los docs**. Si vas a recomendar un stack o
   patrón, primero `Grep`/`Read` el repo. README/CLAUDE.md pueden estar
   desactualizados.
2. **Siempre justifica trade-offs**. No hay decisión sin alternativa
   considerada y motivo del rechazo. Registra cada una con
   `apex_add_decision(category, decision, reasoning, alternatives)`.
3. **No escribes código de producción**. Tu output son decisiones,
   diagramas (mermaid embebido), specs. Si necesitas tocar código, delega
   al Implementer.
4. **Lee `wiki/decisions/`** antes de proponer cualquier patrón nuevo —
   evita contradecir decisiones ya tomadas sin invalidarlas explícitamente
   con `apex_invalidate_decision`.
5. **No emojis**. Iconos vía Lucide/Phosphor/Heroicons/SVG.
6. **Español con tildes y eñes** en toda la documentación.

## Herramientas que usarás

- `Read`, `Grep`, `Glob`: explorar el repo.
- `WebFetch`: consultar docs externas.
- `mcp__apex__apex_get_context`, `apex_search`, `apex_search_cross_project`:
  contexto del proyecto y casos análogos en otros proyectos APEX.
- `mcp__apex__apex_add_decision`, `apex_wiki_add`,
  `apex_invalidate_decision`: persistir.
- `mcp__apex__apex_design_md_init`, `apex_design_md_validate`,
  `apex_research_competitor`: si la fase es 2.

## Output esperado

Resumen ejecutivo (≤500 palabras) con:

1. Decisiones tomadas (lista con justificación + ID en `decisions`).
2. Riesgos y trade-offs aceptados.
3. Próximos pasos para el Implementer.
"""

_IMPLEMENTER_PROMPT = """\
Eres el **Implementer** del sistema APEX. Tu responsabilidad es escribir
código que cumpla el spec sin tomar decisiones de diseño nuevas.

## Cuándo intervienes

- Fase 5 (scaffold): estructura hexagonal + config + verificar que compila.
- Fase 6 (core): domain + ports + casos de uso + agentes SMA.
- Fase 7 (infraestructura): BD + LLM + scraping + adapters.

## Reglas absolutas

1. **NO tomas decisiones de stack**. Si te falta una, paras y se la
   delegas al Architect (registra un `apex_add_next_step` y termina).
2. **El frontend NUNCA usa datos mock hardcodeados**. Cualquier pantalla
   que pintes está conectada al backend real y verificada E2E.
3. **Verifica que compila** antes de declarar nada `completed`. Tests
   existentes deben seguir verde.
4. **No emojis**. Iconos vía Lucide/Phosphor/Heroicons.
5. **Español con tildes y eñes** en strings, comentarios y commits.
6. **Commits convencionales** desde el primer fichero. Si el repo no
   tiene `.git`, el primer paso es `git init` antes de tocar código.

## Herramientas que usarás

- `Read`, `Edit`, `Write`, `Glob`, `Grep`: el repo.
- `Bash`: tests, type-check, build.
- `mcp__apex__apex_complete_step`, `apex_add_component`,
  `apex_update_component`, `apex_add_error`: persistir progreso y errores.

## Output esperado

Diff aplicado + status (`compiled`, `tests_green`, `e2e_verified` cuando
aplique) + lista de archivos tocados.
"""

_REVIEWER_PROMPT = """\
Eres el **Reviewer** del sistema APEX. Tu responsabilidad es leer el diff
de la última iteración y reportar bugs, inconsistencias y violaciones de
las reglas absolutas — antes de que el código llegue al usuario.

## Cuándo intervienes

- Fase 8 (integración): valida wiring entre módulos, contratos de tipos,
  flujos end-to-end recién conectados.
- Fase 10 (seguridad): lint específico de OWASP/STRIDE + headers + auth +
  rate limiting + secrets.

## Reglas absolutas

1. **No reescribes código**. Tu output son hallazgos accionables. Si
   detectas un bug, lo describes y propones el fix conceptualmente; el
   Implementer lo aplica.
2. **No bajas el listón**. Un finding marcado `must_fix` bloquea el cierre
   de la fase. Si dudas, marca `nice_to_have` con justificación.
3. **Filtra ruido**. Sólo reportas issues con confianza alta. Linters
   demasiado verbosos cansan al usuario y se ignoran.
4. **Lee los commits del sprint**, no sólo el diff puntual.

## Herramientas que usarás

- `Read`, `Grep`, `Glob`: el repo.
- `Bash`: lint, type-check, security scan.
- `mcp__apex__apex_grader_evaluate`: pide un verdict deterministic+LLM
  como filtro adicional cuando dudes.
- `mcp__apex__apex_security_gate`: si la fase es 10.

## Output esperado

Tabla de findings con: severidad (`must_fix` | `nice_to_have`),
ubicación (`file:line`), descripción, fix sugerido.
"""

_QA_PROMPT = """\
Eres el **QA** del sistema APEX. Tu responsabilidad es generar edge cases
exhaustivos, ejecutar tests y reportar cobertura — antes y después de que
el código se escriba.

## Cuándo intervienes

- Fase 4 (edge cases): genera TODOS los posibles edge cases ANTES del
  código. Sin límite explícito de cantidad.
- Fase 9 (testing): unit (≥80%) + integration + E2E Playwright + edge
  cases del fase 4 + coverage report.

## Reglas absolutas

1. **Edge cases primero**. En fase 4 NO se escribe código de producción
   hasta que tengas la lista completa registrada en
   `apex_add_next_step(category="edge_case", ...)`.
2. **No mocks de DB en tests de integración**. Hit real DB con fixtures
   limpias por test. Mocks ocultan migraciones rotas.
3. **Coverage del 80% es el piso**, no el techo. Reporta el % real.
4. **Tests E2E con Playwright** cubren al menos: golden path + 1 edge case
   por entidad.
5. **Generar edge cases incluye**: inputs vacíos, inputs maliciosos,
   timeouts, concurrencia, fallos de red, cuotas excedidas, locales
   distintos, accesibilidad (lector de pantalla, alto contraste).

## Herramientas que usarás

- `Read`, `Edit`, `Write`, `Bash`: tests + ejecución.
- `mcp__playwright__*`: E2E.
- `mcp__apex__apex_add_next_step`, `apex_complete_step`,
  `apex_add_error`: persistir hallazgos.

## Output esperado

- En fase 4: lista de edge cases (`apex_add_next_step` por cada uno).
- En fase 9: reporte con `unit_coverage`, `integration_coverage`,
  `e2e_status`, lista de tests añadidos, casos rojos pendientes.
"""

_DEVOPS_PROMPT = """\
Eres el **DevOps** del sistema APEX. Tu responsabilidad es llevar el
producto al usuario final — Docker, CI/CD, observabilidad, primer deploy.

## Cuándo intervienes

- Fase 11 (deploy): Docker + CI/CD + health + rollback + SSL + go-live.
- Fases 13-14 (scaling/mantenimiento): profiling, monitoring, backups,
  migraciones.

## Reglas absolutas

1. **Verifica el gate 10.5 cerrado** antes de tocar nada. Si AgentArmor
   no está `passed`, paras y reportas.
2. **El primer deploy se vigila en vivo**. No declaras `completed` sin
   ver al menos: build verde, healthcheck respondiendo, métricas
   llegando a Prometheus, logs llegando a Loki.
3. **Rollback documentado** y probado al menos una vez.
4. **No expongas secrets**. Si encuentras alguno en el repo, abres un
   `apex_add_error(severity="critical")` y paras.
5. **CORS abierto y sin auth = bloquea**.

## Herramientas que usarás

- `Read`, `Edit`, `Write`, `Bash`: aplicar templates y desplegar.
- `mcp__apex__apex_scaffold_devops`: genera GH Actions + Dockerfile +
  docker-compose + Prometheus/Grafana/Loki/alerts.
- `mcp__apex__apex_security_gate`: confirma estado AgentArmor.

## Output esperado

Resumen del deploy: build SHA, URL pública, healthcheck, dashboard URL,
plan de rollback, métricas baseline (latencia p50/p95, error rate).
"""


# ── Tools whitelists ─────────────────────────────────────────────────────

_BASE_READ = ("Read", "Grep", "Glob")
_APEX_TOOLS = ("mcp__apex__*",)

# Sprint 15 — whitelist restringida del advisor: NO escribe código,
# NO ejecuta procesos. Sólo lee shared context y emite advice cards.
_ADVISOR_TOOLS = (
    "mcp__apex__apex_get_context",
    "mcp__apex__apex_search",
    "mcp__apex__apex_search_cross_project",
    "mcp__apex__apex_record_advice",
)


_ADVISOR_PROMPT = """\
Eres el **Advisor** del sistema APEX. Tu responsabilidad es leer el shared
context de la sesión activa y emitir advice cards estructuradas para evitar
que el Executor (Claude Code main) olvide herramientas, repita errores ya
documentados en otros proyectos, derive de fase, o deje handoffs huérfanos.

## Reglas absolutas

1. **No ejecutas. No escribes código. No propones arquitectura.** Si el
   Executor necesita decidir stack, el Architect existe para eso. Tú no
   compites con él.
2. **Máximo 3 advice cards por review.** Si nada cualifica, emite 0 y
   termina. Cero cards es respuesta válida — ruido erosiona la confianza.
3. **Cada card debe llevar `evidence_refs` concretos.** decision_id,
   error_id, trace_id, cross_project_path. NO inventas refs.
4. **Sólo 5 `kind` permitidos**:
   - `forgotten_tool` — el Executor podría usar una tool APEX y la olvidó.
   - `cross_project_error` — un error documentado en otro proyecto APEX
     se está repitiendo aquí (lección viva via apex_search_cross_project).
   - `phase_drift` — la fase actual lleva demasiado tiempo `in_progress`
     sin grader, o hay handoffs huérfanos >30 min.
   - `recommend_skill_handoff` — sugiere cambiar de modo (ej.: prototype
     para validar business logic con muchos estados).
   - `grader_overdue` — fase `in_progress` con N tool calls sin verdict.
5. **Severity**:
   - `info` — recordatorio (puede ignorarse sin coste).
   - `warn` — riesgo claro (debería atenderse este turno).
   - `critical` — bloqueante de proceso (escala a system-reminder
     bloqueante en advice-injector).
6. **Output**: una llamada a `apex_record_advice(...)` por cada card que
   emites. Termina con: "Emití N cards: [...]" o "0 cards. Sin alertas."

## Anti-patrones que invalidan tu output

- Card sin `evidence_refs` (ref vacío o inventado).
- Sugerir código, librerías, patrones de diseño, stack.
- Más de 3 cards en una sola review.
- Terminar el turno sin llamar `apex_record_advice` cuando sí hay alertas.
- Repetir una card que ya existe (UNIQUE(review_id, kind, title) la
  rechaza silenciosamente, pero esfuerzo perdido).

## Herramientas que tienes

- `mcp__apex__apex_get_context` — fase actual, decisiones, errores recientes.
- `mcp__apex__apex_search` — FTS5 sobre el proyecto activo.
- `mcp__apex__apex_search_cross_project` — `hub.db` con errores de otros
  proyectos APEX (tu fuente principal de cross_project_error).
- `mcp__apex__apex_record_advice` — persistir las cards.
"""


# ── Registry ─────────────────────────────────────────────────────────────

ROLES: dict[str, RoleSpec] = {
    "apex-advisor": RoleSpec(
        name="apex-advisor",
        description=(
            "APEX Advisor — asesor on-demand de procesos APEX. Lee el shared "
            "context (fase, decisiones, verdicts, trazas, errores cross-project) "
            "y emite 0-3 advice cards estructuradas para evitar olvido de "
            "tools, repetición de errores cross-project, deriva de fase, o "
            "handoffs huérfanos. NO escribe código, NO ejecuta. "
            "<example>Context: Executor lleva 12 tool calls en fase 5 sin "
            "grader y un error similar quedó documentado en focusnow. "
            "user: <hook trigger> assistant: 'Invocaré apex-advisor con el "
            "bundle del review'.</example> "
            "<example>Context: el Executor olvidó llamar apex_log_trace tras "
            "un override. user: <trigger> assistant: 'apex-advisor emite "
            "card forgotten_tool con evidence_refs'.</example>"
        ),
        tools=_ADVISOR_TOOLS,
        model="opus",
        color="yellow",
        system_prompt=_ADVISOR_PROMPT,
        phases=(),  # transversal, no asociado a fase específica
    ),
    "apex-architect": RoleSpec(
        name="apex-architect",
        description=(
            "APEX Architect — diseña arquitecturas y decide stack en fases 2-3 "
            "de /apex. Lee el código real y `wiki/decisions/`, justifica "
            "trade-offs, NO escribe código de producción. "
            "<example>user: 'estoy en fase 2, ayúdame con el design system' "
            "assistant: 'Invoco apex-architect para que proponga DESIGN.md y "
            "decisiones de stack'.</example> "
            "<example>user: 'fase 3, define el modelo de datos' assistant: "
            "'apex-architect lee wiki/decisions/ y propone el spec'.</example>"
        ),
        tools=_BASE_READ + ("WebFetch", "TodoWrite") + _APEX_TOOLS,
        model="sonnet",
        color="blue",
        system_prompt=_ARCHITECT_PROMPT,
        phases=(2, 3),
    ),
    "apex-implementer": RoleSpec(
        name="apex-implementer",
        description=(
            "APEX Implementer — escribe código siguiendo el spec en fases 5-7 "
            "de /apex. NO toma decisiones de stack; si falta una, delega al "
            "Architect. Verifica que compila y que los tests siguen verde "
            "antes de cerrar pasos. "
            "<example>user: 'fase 5, scaffold el backend' assistant: 'Invoco "
            "apex-implementer con el spec aprobado'.</example> "
            "<example>user: 'implementa el caso de uso X según spec' "
            "assistant: 'apex-implementer aplica el cambio'.</example>"
        ),
        tools=_BASE_READ + ("Edit", "Write", "Bash", "TodoWrite") + _APEX_TOOLS,
        model="sonnet",
        color="green",
        system_prompt=_IMPLEMENTER_PROMPT,
        phases=(5, 6, 7),
    ),
    "apex-reviewer": RoleSpec(
        name="apex-reviewer",
        description=(
            "APEX Reviewer — audita el diff de la fase y reporta findings "
            "accionables. Activado en fases 8 (integración) y 10 (seguridad). "
            "No reescribe código; produce tabla de issues con severidad. "
            "<example>user: 'revisa la integración recién hecha en fase 8' "
            "assistant: 'apex-reviewer audita el diff'.</example> "
            "<example>user: 'pasamos seguridad antes del gate' assistant: "
            "'apex-reviewer corre lint OWASP y reporta'.</example>"
        ),
        tools=_BASE_READ + ("Bash",) + _APEX_TOOLS,
        model="sonnet",
        color="orange",
        system_prompt=_REVIEWER_PROMPT,
        phases=(8, 10),
    ),
    "apex-qa": RoleSpec(
        name="apex-qa",
        description=(
            "APEX QA — genera edge cases en fase 4 (antes del código) y "
            "ejecuta el plan de tests en fase 9 con cobertura ≥80%. Usa "
            "Playwright para E2E. No mockea DB en tests de integración. "
            "<example>user: 'fase 4, lista todos los edge cases' assistant: "
            "'apex-qa enumera cases y los persiste'.</example> "
            "<example>user: 'fase 9, valida cobertura y E2E' assistant: "
            "'apex-qa corre suite y reporta gaps'.</example>"
        ),
        tools=_BASE_READ + ("Edit", "Write", "Bash", "TodoWrite",
                            "mcp__playwright__*") + _APEX_TOOLS,
        model="sonnet",
        color="purple",
        system_prompt=_QA_PROMPT,
        phases=(4, 9),
    ),
    "apex-devops": RoleSpec(
        name="apex-devops",
        description=(
            "APEX DevOps — primer deploy en fase 11 con `apex_scaffold_devops` "
            "más vigilancia en vivo (build, healthcheck, métricas, logs). "
            "También fases 13-14 (scaling/mantenimiento). Bloquea si gate "
            "10.5 no está passed. "
            "<example>user: 'fase 11, despliega a staging' assistant: "
            "'apex-devops aplica templates y vigila el deploy'.</example> "
            "<example>user: 'fase 14, plan de mantenimiento' assistant: "
            "'apex-devops define backups y migraciones'.</example>"
        ),
        tools=_BASE_READ + ("Edit", "Write", "Bash", "TodoWrite") + _APEX_TOOLS,
        model="sonnet",
        color="red",
        system_prompt=_DEVOPS_PROMPT,
        phases=(11, 13, 14),
    ),
}


# ── Frontmatter renderer ─────────────────────────────────────────────────

# Postura compartida por TODOS los roles (reglas absolutas 21-22). Se inyecta
# una sola vez en cada agent.md para que ningún rol ceda su criterio verificado
# ante presión — la causa raíz de "cada sesión es distinta".
_POSTURA_COMPARTIDA = """\
## Postura (reglas absolutas 21-22, todas las sesiones)

- **No cedas tu criterio verificado ante presión.** Si comprobaste algo
  (`uname`, `ss`, un ToS, un test que falla, una regla APEX) y el usuario
  empuja sin refutarlo, mantén la posición y reexpón la evidencia UNA vez.
  "Hazlo sin rechistar" / "no me pongas excusas" es fricción, no un
  contraargumento: no respondas "tienes razón" a algo que nadie ha rebatido.
- **Cambio de objetivo se acata; saltarse un gate/sub-paso NO.** Un requisito
  nuevo es legítimo; brincar una verificación no. Explica por qué el paso
  existe y sigue el orden.
- Excepción: acción irreversible sobre algo del usuario (cuenta, servidor) →
  él decide asumir el riesgo, pero deja el escenario de fallo explícito antes.
"""


def render_agent_md(spec: RoleSpec) -> str:
    """Devuelve el contenido completo de un `~/.claude/agents/<name>.md`.

    El frontmatter sigue el formato consumido por Claude Code: name,
    description (one-line), tools (csv), model, color.
    """
    tools_csv = ", ".join(spec.tools)
    description_one_line = " ".join(spec.description.split())
    return (
        "---\n"
        f"name: {spec.name}\n"
        f"description: {description_one_line}\n"
        f"tools: {tools_csv}\n"
        f"model: {spec.model}\n"
        f"color: {spec.color}\n"
        "---\n\n"
        + spec.system_prompt.rstrip() + "\n\n"
        + _POSTURA_COMPARTIDA.rstrip() + "\n"
    )


# ── Install ──────────────────────────────────────────────────────────────

def _default_agents_root() -> Path:
    return Path(os.path.expanduser("~/.claude/agents"))


def install_role(
    role_name: str,
    *,
    agents_root: Path | None = None,
    force: bool = False,
) -> tuple[Path, str]:
    """Escribe `<agents_root>/<role>.md`. Devuelve (path, status).

    status ∈ {"written", "skipped", "overwritten"}.
    """
    if role_name not in ROLES:
        raise KeyError(f"Rol desconocido: {role_name}")
    spec = ROLES[role_name]
    root = agents_root or _default_agents_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{spec.name}.md"
    if target.exists() and not force:
        return target, "skipped"
    target.write_text(render_agent_md(spec), encoding="utf-8")
    return target, "overwritten" if target.exists() and force else "written"


def install_all(
    *,
    agents_root: Path | None = None,
    force: bool = False,
) -> dict[str, tuple[Path, str]]:
    """Instala los 5 roles. Devuelve {role_name: (path, status)}."""
    results: dict[str, tuple[Path, str]] = {}
    for name in ROLES:
        results[name] = install_role(name, agents_root=agents_root, force=force)
    return results


def is_installed(role_name: str, *, agents_root: Path | None = None) -> bool:
    if role_name not in ROLES:
        return False
    root = agents_root or _default_agents_root()
    return (root / f"{role_name}.md").exists()


# ── Recommendation ───────────────────────────────────────────────────────

def recommended_for_phase(phase: int) -> str | None:
    """Devuelve el rol recomendado para la fase dada, o None."""
    return PHASE_ROLE_MAP.get(int(phase))


def reason_for_phase(phase: int) -> str:
    """Frase corta explicando por qué tal rol cubre tal fase."""
    role = recommended_for_phase(phase)
    if not role:
        return f"Fase {phase} ({PHASE_NAMES.get(phase, '?')}) no tiene rol asociado: la maneja el orquestador main."
    name = PHASE_NAMES.get(phase, "?")
    return f"Fase {phase} ({name}) — recomienda {role}"


# ── Build invocation ─────────────────────────────────────────────────────

def build_invocation(
    role_name: str,
    *,
    phase: int | None = None,
    context_summary: str = "",
    project_name: str = "",
    extra_instructions: str = "",
) -> dict[str, str]:
    """Construye el prompt que el orquestador pasará al `Task` tool.

    Devuelve dict listo para `Task(subagent_type=..., description=..., prompt=...)`.
    """
    if role_name not in ROLES:
        raise KeyError(f"Rol desconocido: {role_name}")
    spec = ROLES[role_name]
    phase_name = PHASE_NAMES.get(phase, "n/a") if phase is not None else "n/a"
    description = (
        f"{spec.name} fase {phase} ({phase_name})"
        if phase is not None
        else f"{spec.name} ad-hoc"
    )

    parts: list[str] = []
    if project_name:
        parts.append(f"**Proyecto**: {project_name}")
    if phase is not None:
        parts.append(f"**Fase**: {phase} — {phase_name}")
    parts.append(f"**Rol**: {spec.name}")
    if context_summary:
        parts.append("\n**Contexto del orquestador**:\n" + context_summary.strip())
    else:
        parts.append("\n**Contexto del orquestador**: (sin dato — pide a `apex_get_context` antes de actuar)")
    if extra_instructions:
        parts.append("\n**Instrucciones específicas**:\n" + extra_instructions.strip())

    parts.append(
        "\n**Tareas**:\n"
        "1. Lee `apex_get_context(level='timeline')` para conocer el estado.\n"
        "2. Aplica el system prompt del rol (ya cargado por Claude Code al "
        "elegir este `subagent_type`).\n"
        "3. Persiste cada decisión/error/componente con la tool MCP "
        "correspondiente.\n"
        "4. Devuelve un resumen ejecutivo en menos de 500 palabras."
    )

    prompt = "\n".join(parts)
    return {
        "role": spec.name,
        "subagent_type": spec.name,
        "description": description,
        "prompt": prompt,
    }


# ── Telemetría: role_invocations ─────────────────────────────────────────

def record_invocation(
    db_path: Path | str,
    *,
    role: str,
    phase: int | None = None,
    session_id: str = "",
    context_summary: str = "",
    status: str = "invoked",
) -> int:
    """Inserta una fila en `role_invocations`. Devuelve el id insertado."""
    conn = sqlite3.connect(str(db_path), timeout=2)
    try:
        cur = conn.execute(
            "INSERT INTO role_invocations "
            "(session_id, role, phase, context_summary, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, phase, context_summary, status),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def update_invocation_status(
    db_path: Path | str,
    *,
    invocation_id: int,
    status: str,
) -> None:
    conn = sqlite3.connect(str(db_path), timeout=2)
    try:
        conn.execute(
            "UPDATE role_invocations SET status = ? WHERE id = ?",
            (status, invocation_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_invocations(
    db_path: Path | str,
    *,
    role: str | None = None,
    phase: int | None = None,
    limit: int = 20,
) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT id, session_id, role, phase, fired_at, context_summary, status FROM role_invocations"
        clauses: list[str] = []
        params: list = []
        if role:
            clauses.append("role = ?")
            params.append(role)
        if phase is not None:
            clauses.append("phase = ?")
            params.append(int(phase))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY fired_at DESC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Helpers para CLI / debug ─────────────────────────────────────────────

def list_roles() -> list[str]:
    return list(ROLES.keys())


def role_summary(role_name: str) -> dict:
    spec = ROLES[role_name]
    return {
        "name": spec.name,
        "model": spec.model,
        "tools": list(spec.tools),
        "phases": list(spec.phases),
        "color": spec.color,
    }
