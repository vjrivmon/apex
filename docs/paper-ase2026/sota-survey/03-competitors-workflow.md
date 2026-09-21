# APEX — Estado del arte y posicionamiento (barrido exhaustivo)

> Deliverable para el paper APEX (ASE 2026, Tools track). Base: 11 refs ya citadas, ~180 candidatos triados a ~23, 10 deep-reads de los trabajos más amenazantes, y 3 veredictos de panel adversarial. Todo lo que sigue se apoya en esos inputs; no se inventa ningún paper.

---

## 1. Veredicto ejecutivo

**La triple-novedad se sostiene, pero con matiz — el panel la declara `claim_holds` en su forma combinatoria y `claim_weakened` en su redacción literal.** El resultado operativo de los tres jueces es idéntico: cada uno de los tres pilares existe por separado en la literatura (a veces en trabajo concurrente de 2026), pero **ningún sistema los combina los tres en un mismo harness sobre un agente comercial sin modificar**. Es más: ni siquiera existe un sistema que combine solo (a)+(b) — la intersección de "tiene phase gate determinista" y "tiene bucle de auto-ajuste" es vacía. El pilar **(b), el bucle de auto-mejora (grader/advisor/doctor/skill-forge), es el único que no está poblado por nadie** y debe cargar el peso de la novedad.

El problema no es la combinación, sino la frase. "No existing system combines (a)+(b)+(c)…" insinúa que cada pierna es novedosa, y eso es falso: **(a) está reproducida casi verbatim por Rel(AI)Build (2026)** sobre el mismo mecanismo PreToolUse de Claude Code y sobre un agente sin modificar, y **(c) está cubierta head-to-head por ProjectMem (2026)** y parcialmente por AgentMemory. Hay que conceder (a) y (c) explícitamente, reconocer la concurrencia, y anclar la novedad en la integración + el bucle (b).

**Frase reescrita recomendada (síntesis de los tres jueces):**

> "El gating determinista pre-LLM (Rel(AI)Build, AgentSpec, Blueprint-First, TDD-Governance) y la memoria persistente cross-project para agentes sin modificar (ProjectMem, AgentMemory) existen cada uno por separado; Rel(AI)Build incluso demuestra gating de fase determinista sobre un Claude Code sin modificar. Lo que ningún sistema previo o concurrente que conozcamos ofrece es un **bucle cerrado de auto-ajuste** — un grader que bloquea transiciones de fase según resultados juzgados, más un advisor que detecta deriva, un doctor que agrupa errores recurrentes en propuestas de regla, y un skill-forge que sintetiza skills a partir de fallos repetidos — **integrado con gates de FASE deterministas Y un hub de memoria cross-project de decisiones/errores, todo sobre un agente comercial sin modificar**. APEX aporta esa integración; su pilar distintivo es el bucle de auto-ajuste, ausente (o presente solo como housekeeping de memoria / ROI auto-medido, no auto-ajuste) en todos los sistemas examinados."

---

## 2. El panorama por eje

### 2.1 Process-phases

**Claim:** un ciclo de vida de software gateado por fases (15 fases explícitas) con gates deterministas-primero mejora el desarrollo agéntico.

El eje está bien establecido como *organizing principle*: MetaGPT y ChatDev (2023) fijaron la idea de "SOP humano como línea de montaje de fases con verificación de artefactos intermedios"; Lifecycle-Aware Code Generation (2025) la cuantifica a nivel de modelo (+75% correctness). Los sistemas prácticos (Spec Kit, BMAD) la llevan a agentes sin modificar. La parte de "fases mejoran el desarrollo" está **corroborada, no refutada** — nadie discute que las fases ayudan; discuten *cómo se enforzan*.

| Work | Year | Qué hace | Overlap con APEX | Threat |
|---|---|---|---|---|
| Rel(AI)Build (Deterministic Control Plane, arXiv 2606.26924) | 2026 | State machine de fases: "phase n falla si n-1 no registró end-timestamp"; gates hard-coded no bypasseables por prompt | Casi verbatim de phase-gate.py sobre Claude Code sin modificar | **Muy alto** |
| Lifecycle-Aware Code Generation (arXiv 2510.24019) | 2025 | Fine-tune + prompt para emitir artefactos ordenados (requisitos, state-machine, pseudocódigo); +75% CodeBLEU | Corrobora la intuición de descomposición por fases (nivel modelo, no harness) | Alto (corrobora) |
| GitHub Spec Kit | 2026 | Constitution→Specify→Clarify→Plan→Tasks→Implement con artefacto por fase; 111k stars, 30+ agentes | Misma forma de flujo por fases; Constitution ≈ reglas durables | Alto |
| BMAD-METHOD | 2025 | Agentes-persona (Analyst/PM/Architect/SM/Dev/QA) con fases gateadas por artefacto + gate de Implementation-Readiness PASS/CONCERNS/FAIL | Casi isomorfo al modelo de fases de APEX | Alto |
| MetaGPT (arXiv 2308.00352) | 2023 | SOPs humanos como línea de montaje de roles que verifican artefactos por fase | Prior art ancla de "proceso como fases ordenadas con verificación de rol" | Alto (must-cite) |
| ChatDev (arXiv 2307.07924) | 2023 | Empresa virtual waterfall design/coding/testing/docs vía chat-chain | Establece el principio de fases ordenadas explícitas | Alto (must-cite) |

### 2.2 Enforcement-harness

**Claim:** la novedad es el enforcement VINCULANTE: un gate determinista (hook) que BLOQUEA transiciones de fase antes de cualquier juicio LLM, más un grader LLM-as-judge y un security gate.

**Este es el eje más saturado de todos.** El triage lo dice sin ambages: la primitiva "gate determinista que bloquea antes de la ejecución/juicio LLM" NO es novedosa en aislamiento — hay un muro de papers 2026 (AgentSpec, ATLAS-RTC, Solver-Aided/Z3, AgentLTL, ClawGuard, LogicGuard DFA…). La única novedad defendible de APEX en este eje es **aplicarlo a transiciones de FASE del SDLC + componerlo con un grader LLM + un security gate**, sobre un agente sin modificar.

| Work | Year | Qué hace | Overlap con APEX | Threat |
|---|---|---|---|---|
| Rel(AI)Build (arXiv 2606.26924) | 2026 | Blocklist + gate predicates (PHASE_ORDER_VIOLATION, SECURITY_SCAN_GATE, REVIEW_GATE) enforzados en PreToolUse/beforeShellExecution failClosed antes del LLM | Mismo mecanismo, mismo agente, mismo "deterministic code, not a prompt" | **Máximo** |
| AgentSpec (ICSE 2026, arXiv 2503.18666) | 2026 | DSL trigger/check/enforce que intercepta acciones del agente ANTES de ejecutar, deniega con overhead ms | Forma generalizada exacta del pre-LLM gate de APEX | Alto (mismo tipo de venue) |
| Blueprint First, Model Second (arXiv 2508.02721) | 2025 | Motor determinista de 5 capas ejecuta un "Execution Blueprint"; LLM nunca decide el path; nodo Double-Check pre-ejecución | Enunciado más limpio de "determinista-primero, LLM no elige el camino" | Alto |
| TDD Governance for Multi-Agent CodeGen (arXiv 2604.26615) | 2026 | Separa "model proposal" de "deterministic engine authority"; motor rehúsa code-gen hasta que exista test fallando | Match estructural más cercano al enforcement de ordering de fase | Alto |
| From Prompts to Contracts (arXiv 2607.08028) | 2026 | Mueve comportamiento determinista a code/manifests/schemas/validators alrededor de un límite LLM reemplazable; aguanta bajo substitución de modelo | Casi idéntico a "gates vinculantes sobre LLM comercial swappable" | Alto |
| RFC #45427 (claude-code issue) | 2025 | Argumenta que los PreToolUse hooks fallan en silencio, los bypassean subagentes y el modelo los reescribe; pide un tool-gate determinista dentro del dispatch | Crítica directa al mecanismo exacto que usa phase-gate.py de APEX | Alto (crítica, no competidor) |
| BMAD-METHOD | 2025 | Gate Implementation-Readiness PASS/CONCERNS/FAIL que bloquea el paso a implementación | Gate por fase, pero es juicio de agente (skippable, ver issue #1101) | Medio-alto |
| GitHub Spec Kit | 2026 | `check-prerequisites.sh` advisory que el LLM decide correr; docs permiten saltar fases a propósito | Gate a nivel convención/prompt, no hard-block | Medio |

### 2.3 Memory-context

**Claim:** store SQLite temporal por proyecto + hub de memoria cross-project que re-inyecta lecciones al arrancar sesión (segundo cerebro, higiene de contexto).

Eje también crowded en dos frentes. La **invalidación temporal bitemporal** (valid_from/invalid_from, patrón Graphiti que APEX ya acredita) está reproducida por varios papers 2026 (Engram, TOKI, TokenMizer) casi como mecanismo equivalente. La **memoria cross-project sobre agente sin modificar** la cubre ProjectMem head-to-head y AgentMemory parcialmente. APEX no puede reclamar ninguna de las dos sub-piezas como invención propia; su fuerza aquí es que la memoria alimenta el bucle (b).

| Work | Year | Qué hace | Overlap con APEX | Threat |
|---|---|---|---|---|
| ProjectMem (arXiv 2606.12329) | 2026 | MCP memory local-first, event-sourced; `~/.projectmem/global/` hereda "library gotchas" cross-project por stack; gate advisory pre-commit; ROI auto-medido | Cross-project store head-to-head con hub.db; mismo premise agente sin modificar | **Muy alto** |
| AgentMemory (rohitg00) | 2026 | MCP TS, SQLite + BM25 + vector + grafo; 12 hooks; consolidación 4-tier; re-inyección SessionStart ~2000tk con RRF; decay Ebbinghaus | Sistema más cercano al pipeline de memoria de APEX (hook-driven, SQLite, budget, retrieval híbrido) | **Muy alto** |
| TokenMizer (arXiv 2606.06337) | 2026 | Proxy transparente: historia como grafo tipado con validez bitemporal, ciclo de 8 estados de supersession, resume token-budgeted vía MCP | Esencialmente el Context DB temporal + handoff progressive-disclosure de APEX como sistema publicado | Alto |
| Engram (arXiv 2606.09900) | 2026 | Motor bi-temporal dual-process: write path sin LLU + path async que extrae (S,P,O) a KG bitemporal; invalida-no-borra; retrieval con salience decay | Refuta head-on el sub-claim de store temporal (mecanismo equivalente; sin code/cross-project) | Alto |
| TOKI (arXiv 2606.06240) | 2026 | Álgebra de operadores bitemporales para contradicción; fila de provenance conserva el fact "perdedor" | El "invalidate, never delete" + audit de APEX, formalizado y generalizado | Alto |
| SWE Context Bench (arXiv 2602.08316) | 2026 | Benchmark de reuse de experiencia previa cross-task (51 repos, 9 lenguajes); retrieval de experiencia mejora accuracy y baja tokens | Ataca la propuesta de valor central (reuse cross-project) como capacidad evaluada; **yardstick esperado** | Alto (benchmark) |

### 2.4 Integrated-system

**Claim:** APEX como harness end-to-end integrado (tool paper) sobre un agente comercial SIN MODIFICAR, combinando gates + bucle de auto-mejora + memoria cross-project.

Aquí el triage aporta el dato más incómodo: **"harness engineering" es ya un área taxonómica nombrada** (Code as Agent Harness, Meta-Harness, RHO). El bundle "envuelve un agente comercial sin modificar con gates+memoria+auto-mejora" es un espacio reconocido, no una invención. La defensa de APEX es la *intersección de los tres pilares* + el framing cross-PROJECT + la evaluación rigurosa (muchos rivales son sistemas GitHub/blog sin evaluación académica).

| Work | Year | Qué hace | Overlap con APEX | Threat |
|---|---|---|---|---|
| OpenCastle (monkilabs) | 2026 | Harness sobre agentes comerciales: quality gates (secret scan, blast-radius, panel majority vote, smoke tests) + roles de equipo virtual + bucle que gradúa lecciones a instrucciones permanentes | Match casi full-stack; solo le falta memoria cross-project explícita | **Muy alto** |
| Claude-Flow / Ruflo (ruvnet) | 2026 | Meta-harness sobre Claude Code/Codex sin modificar: 100+ role agents, memoria vector HNSW con namespace compartido, routing con coste, circuit breakers, release gates | Prior art a nivel SISTEMA que solapa casi cada cláusula salvo SDLC-por-fases + cross-PROJECT | **Muy alto** |
| Meta-Harness (Stanford, arXiv 2603.28052) | 2026 | Optimiza el scaffolding (prompts, memory, retrieval, tools, evaluators) alrededor de un modelo FIJO vía propose→score→Pareto; 6x gap del harness solo | Reclama el espinazo "mejora el harness sobre modelo sin modificar" y define "harness" igual | Alto |
| RHO (Microsoft, arXiv 2606.05922) | 2026 | Método self-supervised que mejora el harness (skills, tools, workflows) desde trayectorias pasadas sin labels; SWE-Bench Pro 59%→78% en una ronda | Nombra "the agent harness" como objeto y lo auto-mejora sobre modelo sin modificar — eje exacto de skill_forge/apex_doctor | Alto |
| Code as Agent Harness (arXiv 2605.18747) | 2026 | Survey que sistematiza "code as agent harness"; lista "regression-free harness improvement" y "shared state consistente" como retos abiertos | Sistematiza el concepto mismo que APEX integra | Alto (must-cite positioning) |
| From Prompts to Contracts (arXiv 2607.08028) | 2026 | Gates code-owned que aguantan bajo substitución de modelo (3 modelos hosted) | Idéntico a "gates vinculantes sobre LLM comercial swappable" | Alto |

---

## 3. Sistemas comparables (comparación directa — la tabla clave)

Leyenda: **sí** / **parcial** / **no**. Columnas = (a) phase gates · (b) blocking determinista pre-LLM · (c) bucle de auto-mejora · (d) memoria cross-project · (e) corre sobre agente comercial sin modificar.

| Sistema | (a) Phase gates | (b) Blocking determinista | (c) Bucle auto-mejora | (d) Memoria cross-project | (e) Agente sin modificar |
|---|---|---|---|---|---|
| **Rel(AI)Build** (2026) | sí | sí | no | no | sí |
| **ProjectMem** (2026) | no | parcial (warns, no block) | no | sí | sí |
| **AgentMemory** (2026) | no | no (PreToolUse observacional) | parcial (housekeeping) | parcial (canal de lecciones filtrado) | sí |
| **BMAD-METHOD** (2025) | sí | no (juicio de agente, skippable) | no | no | sí |
| **GitHub Spec Kit** (2026) | sí | parcial (script advisory) | no | no | sí |
| **Blueprint First** (2025) | parcial | sí | no | no | no (motor bespoke) |
| **TDD Governance** (2026) | parcial | sí | no | no | no (orquestador bespoke) |
| **AgentSpec** (ICSE 2026) | no | sí | no | no | no (instrumenta LangChain) |
| **OpenCastle** (2026) | parcial (roles/gates) | parcial | parcial (gradúa lecciones) | no | sí |
| **Claude-Flow / Ruflo** (2026) | no | parcial (release gates) | parcial | parcial (namespace compartido intra) | sí |
| **Lifecycle-Aware CodeGen** (2025) | parcial | no | no | no | no (fine-tune) |
| **APEX** | **sí** | **sí** | **sí** | **sí** | **sí** |

**Lectura de la tabla:** ninguna fila salvo APEX tiene la columna (c) en **sí**. Las únicas "parcial" en (c) — AgentMemory, OpenCastle, Claude-Flow — son *housekeeping de memoria* (decay/consolidación) o *graduación de lecciones a instrucciones*, no un bucle que juzga resultados y **ajusta las propias reglas/skills del harness** con un grader que bloquea. Ese es el discriminador. Además, la intersección {(a)=sí} ∩ {(c)≠no} está vacía: los que tienen gates de fase (Rel(AI)Build, BMAD, Spec Kit) no tienen auto-ajuste, y los que tienen algo de auto-ajuste no tienen gates de fase deterministas.

---

## 4. El hueco defendible

APEX es el único sistema que combina, **en un harness sobre Claude Code sin modificar**:

1. **(a)** gates de fase **deterministas-primero** (hook PreToolUse que veta `apex_set_phase` antes de cualquier juicio LLM), ligados a un **ciclo de vida de 15 fases** (0-socrático → 14-mantenimiento) + gate 10.5 de seguridad AgentArmor;
2. **(b)** un **bucle cerrado de auto-ajuste** — grader (verdicts que hard-bloquean), advisor (mina deriva y recomienda handoffs), apex-doctor (agrupa errores recurrentes en propuestas de regla), skill-forge (sintetiza skills desde fallos repetidos);
3. **(c/d)** un **hub de memoria cross-project** (hub.db + `apex_search_cross_project`) que re-inyecta lecciones al arrancar sesión, sobre un store temporal bitemporal por proyecto.

**¿Encontró el panel un refutador? No de la combinación, sí de piernas individuales.** El refutador más peligroso es **Rel(AI)Build (2026)**: posee (a) *completa y rigurosa* (gate de fase determinista, mismo mecanismo PreToolUse, agente sin modificar) e incluso añade un ángulo supply-chain/audit que APEX no tiene. Pero **carece de (b)** (su único ítem adaptativo, thresholds Jaccard, es explícitamente "pending calibration") **y de (c)** (comparte ficheros de config por content-addressing — distribución de artefactos, no un hub de decisiones/errores). El runner-up sobre la *combinación* es ProjectMem: tiene (c)+(e) y un gate determinista, pero su gate **avisa, no bloquea**, no tiene noción de fases, y su "score" auto-mide ROI en vez de auto-ajustar.

**El pivot honesto que debe hacer el paper:**

- **Conceder (a)** como prior/concurrent art (Rel(AI)Build, AgentSpec, Blueprint, TDD-Governance) — no reclamar el gate determinista pre-LLM como invención.
- **Conceder (c/memoria)** como prior art (ProjectMem head-to-head, AgentMemory adyacente) — no reclamar el hub cross-project como categoría nueva.
- **Anclar la novedad en (b)** — el bucle de auto-ajuste dirigido por resultados juzgados — y en la **integración tri-pilar** sobre un agente sin modificar, ligando el gate determinista específicamente a **transiciones de FASE** (lo que separa la multitud del deterministic-blocking, que no tiene fases, de la multitud del phase-gating, que no es determinista).
- **Reconocer la concurrencia** ("no prior or concurrent system we are aware of…") en vez de "no existing system" — muchos rivales son 2026.
- **Diferenciar por evaluación rigurosa**: Spec Kit, BMAD, Claude-Flow, OpenCastle, AgentMemory, ProjectMem son sistemas GitHub/blog **sin evaluación académica**. Un tool-paper puede diferenciarse ahí, pero los reviewers los citarán como prior art de las ideas.

---

## 5. Papers a citar (por eje)

Todos son NUEVOS (no están entre los 11 ya citados). Verificar IDs marcados con ⚠ antes de citar (ver §6).

### process-phases
- **Rel(AI)Build — A Deterministic Control Plane for LLM Coding Agents** (2026, arXiv 2606.26924 ⚠) — closest concurrent work sobre gating de fase determinista pre-LLM en agente sin modificar; must-cite y must-distinguish.
- **Lifecycle-Aware Code Generation** (2025, arXiv 2510.24019) — evidencia empírica independiente de que descomponer en fases SE ordenadas mejora correctness (+75%); corrobora la intuición.
- **MetaGPT** (2023, arXiv 2308.00352) — ancla de prior art "SOP como fases con verificación de rol".
- **ChatDev** (2023, arXiv 2307.07924) — baseline del principio de fases ordenadas explícitas.
- **GitHub Spec Kit** (2026, github.com/github/spec-kit) — analog tooling más adoptado del flujo por fases; defensa: gates a nivel convención/prompt.
- **BMAD-METHOD** (2025, github.com/bmad-code-org/bmad-method) — modelo de fases casi isomorfo con gate PASS/CONCERNS/FAIL; diferenciador: gate es juicio de agente (issue #1101).

### enforcement-harness
- **AgentSpec** (ICSE 2026, arXiv 2503.18666) — prior art más fuerte del gate determinista pre-ejecución; mismo tipo de venue SE. Must-cite.
- **Blueprint First, Model Second** (2025, arXiv 2508.02721) — enunciado más limpio de "LLM nunca decide el path + gate de validación pre-ejecución".
- **TDD Governance for Multi-Agent Code Generation** (2026, arXiv 2604.26615 ⚠) — separa model-proposal de deterministic-engine-authority; match estructural del enforcement de ordering.
- **From Prompts to Contracts: Harness Engineering for Auditable Enterprise LLM Agents** (2026, arXiv 2607.08028 ⚠) — gates code-owned que aguantan bajo substitución de modelo.
- **RFC: Deterministic tool gate (claude-code issue #45427)** (2025) — crítica directa a la insuficiencia de los PreToolUse hooks; citar como limitación conocida asumida.

### memory-context
- **ProjectMem** (2026, arXiv 2606.12329 ⚠) — prior art concurrente más cercano de memoria cross-project sobre agentes MCP sin modificar. Must-cite, must-distinguish.
- **AgentMemory** (2026, github.com/rohitg00/agentmemory) — sistema más cercano al pipeline de memoria (hook-driven, SQLite, retrieval híbrido, re-inyección SessionStart ~2000tk).
- **TokenMizer** (2026, arXiv 2606.06337 ⚠) — Context DB temporal + handoff como sistema publicado.
- **Engram — Less Context, More Accuracy** (2026, arXiv 2606.09900 ⚠) — motor bi-temporal, invalida-no-borra; equivalente al sub-claim de store temporal.
- **TOKI — A Bitemporal Operator Algebra** (2026, arXiv 2606.06240 ⚠) — formaliza "invalidate, never delete" con audit; generaliza el patrón de APEX.
- **SWE Context Bench** (2026, arXiv 2602.08316 ⚠) — benchmark de reuse de experiencia cross-task; yardstick de evaluación esperado por reviewers.

### integrated-system
- **Code as Agent Harness** (2026, arXiv 2605.18747 ⚠) — survey que sistematiza el concepto; must-cite para positioning.
- **Meta-Harness** (Stanford, 2026, arXiv 2603.28052 ⚠) — optimiza scaffolding sobre modelo fijo; define "harness" igual.
- **RHO — Evolving Agents in the Dark** (Microsoft, 2026, arXiv 2606.05922 ⚠) — auto-mejora del harness desde trayectorias sin labels; eje exacto de skill_forge/apex_doctor.
- **OpenCastle** (2026, github.com/monkilabs/opencastle) — match casi full-stack; le falta memoria cross-project.
- **Claude-Flow / Ruflo** (2026, github.com/ruvnet/ruflo) — meta-harness sobre Claude Code; reviewers exigirán diferenciación.

---

## 6. Riesgos y caveats

- **IDs arXiv 2026 con month-codes implausibles (⚠).** El propio triage advierte: varios IDs usan `26xx` (p.ej. 2606.*, 2607.*, 2604.*, 2603.*, 2605.*, 2602.*) que corresponderían a meses futuros (junio/julio 2026 y posteriores). **Verificar la existencia de cada uno antes de meterlo en references.bib** — algunos podrían no existir o tener el ID mal. Prioridad de verificación: Rel(AI)Build (2606.26924), ProjectMem (2606.12329), Engram (2606.09900), TOKI (2606.06240), TokenMizer (2606.06337), RHO (2606.05922), From-Prompts-to-Contracts (2607.08028), Meta-Harness (2603.28052), Code-as-Agent-Harness (2605.18747), TDD-Governance (2604.26615), SWE-Context-Bench (2602.08316).
- **Rivales sin evaluación académica.** Spec Kit, BMAD, Claude-Flow/Ruflo, OpenCastle, AgentMemory, ProjectMem son GitHub/blog. Se citan como prior art *de las ideas*, no como baselines evaluados. No atribuirles métricas que no publican.
- **Texto completo no leído en todos.** MetaGPT y ChatDev se marcaron `must_deep_read: false` (bien conocidos). Code-as-Agent-Harness también `false`. Para el resto hay deep-read, pero solo de 10 de los ~23; sistemas como TokenMizer/Engram/TOKI/SWE-Context-Bench/OpenCastle/Claude-Flow/Meta-Harness/RHO/Spec-Kit tienen ficha de triage pero **no deep-read completo** — sus valores en la tabla §3 provienen de one-liners de triage, no de lectura íntegra. Verificar antes de afirmar en el paper.
- **Claim status "unknown" a resolver manualmente:** (1) si algún paper 2026 combina realmente (a)+(b) — el panel dice que no, pero solo cubre los 10 deep-reads; (2) si OpenCastle/Claude-Flow tienen memoria cross-PROJECT real (no solo intra-project namespace); (3) si el "self-improvement" de RHO/Meta-Harness ajusta *reglas de gate* o solo *skills/prompts* (importa para diferenciar de skill-forge vs advisor/doctor).
- **La pierna (a) está reproducida; no sobre-reclamar.** El mayor riesgo de review es que un reviewer cite Rel(AI)Build o AgentSpec y diga "el gate determinista pre-LLM no es nuevo". La defensa ya está en §4: conceder y pivotar a (b)+integración.
- **El benchmark que faltará.** SWE Context Bench (si existe) es el yardstick que los reviewers esperarán para el reuse cross-project. Si el paper no evalúa contra él o algo equivalente, anticipar la crítica en Threats-to-Validity.

---

## 7. Cómo buscar en Consensus / arXiv (guía práctica)

Queries concretas por eje para que el autor verifique y amplíe él mismo.

**process-phases**
- arXiv: `all:"phase-gated" AND all:"code generation" AND all:agent`
- arXiv: `all:"software development lifecycle" AND all:"LLM agent" AND all:phases`
- Consensus: *"Does decomposing code generation into ordered software-engineering phases improve correctness?"*
- Consensus: *"Do phase gates improve reliability of multi-agent software development?"*

**enforcement-harness**
- arXiv: `all:"runtime enforcement" AND all:"LLM agent" AND (all:deterministic OR all:"before execution")`
- arXiv: `all:"PreToolUse" OR all:"tool call" AND all:gate AND all:agent`
- Consensus: *"Can deterministic runtime gates block unsafe LLM-agent actions before execution?"*
- Google Scholar / arXiv listing: `cat:cs.SE AND deterministic gate agent 2025..2026`

**memory-context**
- arXiv: `all:"cross-project" AND all:memory AND all:"coding agent"`
- arXiv: `all:bitemporal AND all:memory AND all:LLM` · `all:"valid time" AND all:"knowledge graph" AND all:agent`
- arXiv: `all:MCP AND all:memory AND all:"SessionStart" OR all:re-injection`
- Consensus: *"Does reusing memory from prior tasks improve coding-agent accuracy?"*

**integrated-system**
- arXiv: `all:"agent harness" AND (all:optimization OR all:"self-improvement")`
- arXiv: `all:"harness engineering" AND all:LLM` · `all:"unmodified" AND all:"coding agent" AND all:hooks`
- Consensus: *"Does optimizing the scaffolding around a fixed LLM improve agent benchmark performance?"*
- GitHub: `topic:claude-code memory` · `topic:agent-harness gates` · `spec-driven development agent`

**Cross-cutting (para la novelty tri-pilar):**
- Buscar simultáneamente los tres términos: `"phase gate" "cross-project memory" "self-improvement" agent harness` — si esta query devuelve algo con los tres, es el refutador que hay que leer antes de someter.
