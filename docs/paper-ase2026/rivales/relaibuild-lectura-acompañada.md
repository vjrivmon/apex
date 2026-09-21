# Rel(AI)Build — lectura acompañada, claim a claim, cruzada contra APEX y las columnas (a)-(e)

> **Paper**: Padmaraj Madatha, *A Deterministic Control Plane for LLM Coding Agents*.
> Happiest Minds Technologies (AIP Centre of Excellence). arXiv:2606.26924v1, 25 jun 2026. 42 pág.
> **Implementación de referencia**: Rel(AI)Build (Node.js).
> **Leído a texto completo** (42/42 pág) el 12 jul 2026. Cero citas de segunda mano: cada verbatim de abajo está copiado del PDF.
>
> **Columnas del design space** (fijadas en `../sota-survey/04-deepread-evidence.md`):
> **a** = phase gates sobre un lifecycle explícito · **b** = blocking determinista pre-LLM ·
> **c** = bucle de auto-mejora dirigido por outcomes · **d** = transferencia de memoria cross-project ·
> **e** = corre sobre un agente sin modificar.
>
> Scoreboard de referencia (del deep-read): **Rel(AI)Build = a:yes · b:yes · c:partial · d:no · e:yes**.
> Tras leer el paper completo, **corrijo (c) de _partial_ a _no_** (justificación en §CLAIM-7).

---

## TL;DR en cinco líneas

1. Rel(AI)Build y APEX **colisionan de frente en (a)+(b)** — su phase-state machine (§4.5) es casi isomorfa a nuestras 14 fases + gates. Ahí es donde MÁS se parece, y donde en pureza determinista **nos gana**.
2. Su fuerte genuino y **gap real nuestro es (b)-supply-chain**: SHA-256 content addressing + HMAC lockfile + audit hash-chained + SBOM/NTIA mapping sobre *las definiciones de agente*. APEX no tiene nada de esto.
3. **(c) y (d) son territorio nuestro sin disputa.** Rel(AI)Build no aprende de outcomes (su "drift detection" es Jaccard sobre el prompt, no un loop) y **lamenta explícitamente** no tener cross-project ("must re-author... multiple times").
4. Su gran concesión, repetida en abstract + §6 + §8 + §10: **"developer outcomes remain future work"**. Neutraliza el ataque "vosotros tampoco medís outcomes" — están en la misma situación y lo admiten como línea central.
5. **Acción para el paper**: citar como concurrent art (jun 2026, un mes antes), conceder (a)+(b), anclar novedad en (a)∩(b)∩(c)∩(d) y en las celdas vacías (a)∩(b)∩(c) y (c)∩(d). Robarles el patrón de conformance-tests como respuesta al reviewer que pida rigor determinista.

---

## Formato de cada entrada

**CLAIM-N** (§sección) — *"cita verbatim"*
→ **Qué es**: paráfrasis neutra.
→ **¿APEX lo suple / mejora / gap suyo real?**
→ **Veredicto + qué hacer en el paper**.

---

### CLAIM-1 — La tesis: la capa config-and-process es una supply chain gobernable (§1.2)

*"The configuration-and-process layer that surrounds an LLM coding agent can be treated as a managed software supply chain, governed **deterministically** and **independently of the underlying harness or model**, addressing critical integrity, traceability, and portability risks that the harness alone does not."*

→ **Qué es**: la tesis entera. Es deliberadamente estrecha ("Our thesis is deliberately narrow. RBAC, sandboxing, and orchestration are established paradigms; we do not claim them as novel").
→ **APEX**: coincidimos en (e) "independent of harness/model" — ambos corremos sobre Claude Code sin tocarlo. Pero nuestra tesis NO es "config como supply chain"; es "un harness que guía el ciclo completo y aprende de sí mismo". Su eje es **integridad/trazabilidad/portabilidad**; el nuestro es **guía + memoria + auto-mejora**. Son tesis ortogonales que se solapan en el mecanismo de gates.
→ **Veredicto**: **concurrent, no competidor directo de tesis**. En Related Work: "Madatha (2026) frames the same surface as a *supply chain* to be secured; APEX frames it as a *lifecycle* to be guided and improved. The mechanisms overlap at the phase gate; the theses do not." No hay que defenderse, hay que delimitar.

---

### CLAIM-2 — Los tres gaps estructurales: config no gobernada, ejecución sin límites, expertise no portable (§1.1)

*"Gap 1: The configuration is unmanaged software... Gap 2: Execution is unbounded... Gap 3: Expertise does not port."*

→ **Qué es**: el motivador. Gap 1 (config copy-pasteada sin provenance), Gap 2 (sin trace requirement→impl→test, sin cap de self-correction), Gap 3 (cada harness tiene su dialecto).
→ **APEX**:
>   - **Gap 1 (config unmanaged)**: **gap suyo real, no lo cubrimos.** APEX no verifica provenance de sus propios SKILL.md/CLAUDE.md con hashes. Nuestra librería (`library_ingest.py`) valida frontmatter y secretos al *ingerir*, pero no hay content-addressing ni lockfile de lo instalado. **Esto es lo más aprovechable de leerlo: es una debilidad concreta de APEX que ellos nombran bien.**
>   - **Gap 2 (execution unbounded)**: **lo cubrimos, y con más lifecycle.** Nuestro grader + phase gates + los 14 pasos son exactamente un límite a la ejecución. Su cap es "3-iteration"; el nuestro es outcome-based (el grader bloquea la transición). Empate mecánico, ventaja nuestra en granularidad de fase.
>   - **Gap 3 (expertise no porta entre dialectos)**: **ojo — su Gap 3 NO es nuestro (d).** Su Gap 3 es *portar la misma config a Cursor/Codex/Windsurf* (compile-to-many, §4.6). Nuestro (d) es *transferir lecciones aprendidas entre proyectos distintos*. Son cosas diferentes con nombres parecidos. **No dejar que un reviewer los confunda**: su "portability" es multi-IDE; nuestra "cross-project" es multi-repo con aprendizaje.
→ **Veredicto**: Gap 1 = **incorporar como limitación honesta nuestra o como future work** ("APEX does not yet content-address its own skill/config artifacts; cf. Madatha 2026"). Gap 3 = **desambiguar en el texto** para que no parezca que resuelven nuestro (d).

---

### CLAIM-3 — Supply chain de definiciones de agente: SHA-256 + HMAC lockfile + audit hash-chained (§4.1, §5, Contribución 1)

*"content addressing (SHA-256, HMAC-stamped lockfiles, hash-chained audit logs) to counter undeclared propagation"* ... *"Every registry resource possesses a SHA-256 hash. The installation process recomputes the hash of fetched content and aborts on mismatch"* ... *"CLI mutations append a JSONL record {timestamp, action, user, cwd, details}... each line carrying a SHA-256 hash of its own content."*

→ **Qué es**: el núcleo diferencial de Rel(AI)Build. Trata cada agente/skill/knowledge-shard como un artefacto de supply chain: hash de contenido, lockfile por proyecto firmado con HMAC, log de auditoría append-only encadenado por hash. Mapea a NTIA SBOM minimum elements (Tabla 8) y SLSA Build Level 2.
→ **APEX**: **GAP SUYO REAL Y LIMPIO.** No tenemos nada equivalente:
>   - APEX tiene un `audit`-ish trail vía `tool_call_log` y `reasoning_traces`, pero **no está hash-encadenado ni es tamper-evident**. Es telemetría, no provenance.
>   - No hay content-addressing de skills. `library_imports(slug, source, sha, ...)` guarda un SHA del import pero **no recomputa-y-aborta en la instalación** — es dedup, no un integrity gate.
>   - No hay lockfile HMAC.
→ **Veredicto**: **conceder sin pelea, es genuinamente suyo.** DOS jugadas posibles:
>   1. *Defensiva (mínima)*: en Related Work, "supply-chain integrity of the agent definitions themselves is orthogonal to APEX's contribution and well-addressed by Madatha (2026); APEX could adopt content-addressing as a complementary layer." Los citamos como quien resuelve un problema adyacente que no atacamos.
>   2. *Ofensiva (roadmap)*: **anotar como Sprint futuro real de APEX** — "content-address + hash-chain los skill/proposal artifacts". Encaja con lo que ya hace `library_ingest` (validación al ingerir) y `skill_forge` (proposals a disco). Sería barato y cierra el flanco antes de que un reviewer lo abra.
> **Nota honesta**: su propio §8 admite que el HMAC default es *machine-local key* → "do not defend against an adversary with direct, privileged access... nor provide Sigstore-grade cryptographic authentication (future work)". O sea: su supply-chain es fuerte contra corrupción accidental/automatizada, **no contra un atacante same-user**. Es sólido pero no bulletproof, y ellos lo dicen. No lo sobredimensiones al concederlo.

---

### CLAIM-4 — Guardrail determinista pre-LLM: tiers + blocklist como IDE runtime hooks (§4.2, §4.3, Contribución 2)

*"a deterministic pre-execution guardrail system enforces tier-based permissions bound to the agent definition's supply chain and enforced prior to LLM invocation, alongside an attack-derived command/path blocklist deployed as IDE runtime hooks (Claude Code PreToolUse, Cursor beforeShellExecution)"*

→ **Qué es**: pillar **(b)** en su forma más pura. Cinco tiers de permisos (readonly→scribe→operations→specialist→orchestrator) como allowlists fail-closed, más una blocklist de regex derivada de incidentes reales (event-stream, Codecov, ua-parser-js, xz-utils) que bloquea `curl|bash`, `git config --global`, `core.hooksPath`, etc. Todo en hooks PreToolUse **antes** de que el LLM actúe.
→ **APEX**: **solape parcial, ventaja suya en pureza.**
>   - APEX tiene `security_gate.py` (AgentArmor 8 capas) + fase 10.5 que **bloquea la fase 11** si alguna capa != passed. Eso es (b). Pero nuestro bloqueo opera a nivel **fase/grader**, no a nivel **cada tool-call pre-ejecución**.
>   - Nuestros roles (`roles.py`) tienen whitelists de tools por subagente — análogo a sus tiers — pero **no fail-closed a nivel hook**; es el subagent spec, que Claude Code respeta pero APEX no *enforces* con un PreToolUse que aborte.
>   - **No tenemos blocklist de comandos derivada de incidentes.** Esto es concreto y adoptable.
→ **Veredicto**: **(b) NO es novedad exclusiva de nadie** (ya lo dice el survey: Rel(AI)Build y OpenCastle lo hacen limpio). Para el paper: **dejar de reclamar (b) como pillar solo**. Su versión de (b) es más granular (per-tool-call, pre-LLM) que la nuestra (per-phase). Si un reviewer dice "APEX's blocking is coarser", es cierto — la respuesta es que APEX **compone** (b) con (c)+(d), no que (b) sea más fino. **Adoptable barato**: la blocklist de la Tabla 4 (curl|bash, git config, core.hooksPath, detached-spawn) es un template DevOps que APEX puede portar directamente — ya está en el roadmap Sprint 19 como "gitleaks template", ampliarlo.

---

### CLAIM-5 — Lifecycle phase-gated con invariantes duras y state machine determinista (§4.5, Appendix C, Contribución 4)

*"A deterministic phase-gated lifecycle whose state machine enforces process invariants (ordering, mandatory delegation, requirement→file→test traceability) and blocks execution upon violation."* Guards (Tabla C1): `PHASE ORDER VIOLATION` (end_ts[n−1] exists), `END WITHOUT START`, `DELEGATION GATE FAILURE`, `REVIEW GATE` (spec-reviewer recorded), `SECURITY SCAN GATE` (securityScan.status = clean), 3-iteration cap. *"Because these checks are hard-coded in the control plane, they cannot be bypassed via persuasive LLM prompting."*

→ **Qué es**: pillar **(a)** en su forma más pura, y **el punto de máximo solape con APEX**. Una LTS sobre fases {0,1,3,4,5,7,8} con 4 HITL pauses. `end_phase(n)` no cierra si faltan invariantes. Rejection/rollback también determinista (HITL_REJECTED, pending re-entry).
→ **APEX**: **colisión frontal. Aquí somos casi el mismo sistema, y ellos lo tienen más blindado.**
>   - Nuestras 14 fases + gate 10.5 = su phase-gated lifecycle. Nuestro `phase_entry_check` + hook `phase-gate.py` = sus guards. Mismo espíritu.
>   - **Diferencia crítica y a nuestro favor sería endeble aquí**: su gate es **código determinista hard-coded** ("cannot be bypassed via persuasive LLM prompting"). **Nuestro grader es un LLM-judge (Sonnet).** Un reviewer adversarial dirá: *"APEX's phase gate delegates the block decision to an LLM verdict, which is exactly the non-deterministic component Madatha argues cannot serve as a trustworthy control (§1.2: 'A non-deterministic component cannot serve as a trustworthy control for another non-deterministic component')."* **Este es el ataque más peligroso del paper contra nosotros.**
→ **Veredicto**: **esto exige respuesta explícita, no concesión pasiva.** Opciones:
>   1. **Reconocer y diferenciar el propósito del gate.** Su gate verifica *invariantes de proceso* (¿se registró la delegación? ¿el scan está limpio? ¿el orden es correcto?) — todo booleano determinista. Nuestro grader verifica *calidad de outcome* (¿el objetivo de la fase se cumplió de verdad?) — que es intrínsecamente semántico y NO se puede hacer con regex. **Son gates de naturaleza distinta**: los suyos son *fail-closed checks*, el nuestro es *outcome judgment*. APEX **también** tiene checks deterministas (el propio `phase-gate.py`, `security_gate.py`, `grader.py` tiene "checks deterministas: git, tests, OS, emojis, Pydantic, Playwright" ANTES del LLM judge). O sea: **APEX ya combina gate determinista + juicio LLM; no es LLM-only.** Decirlo claramente mata el ataque.
>   2. **Robarles la munición de conformance**: ellos validan sus invariantes con conformance tests (N=10/15/20 injected violations, §6). APEX puede hacer lo mismo para su capa determinista y **debería mencionarlo** — "the deterministic sub-gates in APEX (git/test/OS/schema checks) are conformance-testable in the same sense as Madatha's guards; the LLM judge sits *above* them for outcome quality, not *instead* of them."
>   3. **No fingir que somos más deterministas que ellos en (a)+(b). No lo somos.** Nuestra ventaja no es determinismo; es (c)+(d) *encima* de fases gateadas. Esa es la frase.

---

### CLAIM-6 — Define-once / compile-to-many con argumento de preservación de governance (§4.6, Appendix B, Contribución 5)

*"A define-once / compile-to-many transformer portable across seven IDE targets, with a governance-preservation argument (Appendix B)."*

→ **Qué es**: una definición canónica Markdown+YAML compilada a Cursor/Claude Code/VS Code/Codex/Windsurf/OpenCode/Kiro, con un argumento semi-formal (Appendix B, no una prueba mecanizada) de que la propiedad de governance P se preserva bajo compilación.
→ **APEX**: **fuera de nuestro scope, y a propósito.** APEX es **mono-harness por diseño** (Claude Code). No compilamos a otros IDEs. Su Gap 3 (multi-dialect) simplemente no es un problema que tengamos porque no lo intentamos.
→ **Veredicto**: **conceder como no-objetivo.** Una frase en Related Work o Threats: "APEX targets a single harness (Claude Code) and does not address multi-IDE portability (cf. Madatha's compile-to-many, §4.6); this is a deliberate scope choice, not a gap." **No es una debilidad si lo enmarcamos como decisión.** El riesgo es que un reviewer pregunte "¿y si el usuario usa Cursor?" — la respuesta honesta es "APEX no lo soporta hoy; el diseño no lo impide pero no está construido". No sobre-prometer.

---

### CLAIM-7 — Drift detection vía Jaccard como "operational risk surface" (§4.4, Contribución 3) — [su (c) supuesto]

*"A tokenisation-normalisation pipeline and drift detection mechanism measuring cosmetic prompt edits as an operational risk surface using Jaccard similarity — a detection mechanism, **not a validated behavioural predictor** (§9.1)."*

→ **Qué es**: normalizan el prompt del agente (CRLF→LF, whitespace) y miden Jaccard contra un baseline humano-revisado. J<0.60 = HIGH = CI block. **Esto es lo único que el deep-read marcó como "(c) partial".**
→ **APEX**: **aquí corrijo el scoreboard.** Leído completo, esto **NO es un self-improvement loop en ningún sentido**:
>   - Detecta que *alguien editó el system prompt del agente* respecto a una versión revisada. Es un **diff detector de configuración**, no un aprendizaje de resultados.
>   - No hay outcome. No hay señal de éxito/fallo de tareas. No hay actualización de comportamiento. Los propios autores lo desclasifican: *"a detection mechanism, not a validated behavioural predictor"* y en §9.1 admiten que ni siquiera está calibrado ("operating defaults pending calibration").
>   - Compárese con APEX (c): `skill_forge` (detecta patrones de fallo → propone skills), `apex_doctor` (3 analizadores → propuestas de mejora), `advisor` (outcome-driven advice), grader verdicts que retroalimentan. **Eso sí es un loop dirigido por outcomes.**
→ **Veredicto**: **(c) de Rel(AI)Build = _no_, no _partial_.** Su "drift detection" está en la columna equivocada — es más un mecanismo de (b)-integridad (detectar tampering del prompt) que de (c)-mejora. Para el paper: **reforzar que (c) es limpio nuestro.** Y usar su propia frase como escudo: si un reviewer dice "Rel(AI)Build también se auto-monitoriza", responder con su verbatim "not a validated behavioural predictor". **Es su disclaimer, no nuestra inferencia — inatacable.**
> *(Mantengo el scoreboard del survey como está publicado — "partial" — pero anoto esta corrección para defenderla de viva voz si hace falta. Cambiar la celda a "no" en la tabla del paper es defendible pero opcional; "partial" ya es suficientemente conservador y no nos perjudica.)*

---

### CLAIM-8 — Cross-project: lo nombran como PROBLEMA, no lo resuelven (§1.1 Gap 3, §8)

*"An organisation that standardises on more than one tool... must re-author and re-maintain the same expertise multiple times."* (§1.1) — planteado como Gap, resuelto solo vía compile-to-many multi-IDE, NO vía aprendizaje entre proyectos.

→ **Qué es**: su tratamiento de la portabilidad de expertise se agota en compilar la *misma* config a varios IDEs. **No hay transferencia de lecciones aprendidas de un proyecto a otro.**
→ **APEX**: **(d) es nuestro sin disputa.** `apex_search_cross_project`, el hub.db, `session-start.py` inyectando lecciones cross-project ("En el intento anterior de FocusNow asumí macOS..."), `skill_forge` D3 (decisiones que aparecen en ≥2 proyectos). Rel(AI)Build no tiene análogo — su lockfile y audit son **per-project** ("A per-project lockfile"), su memoria no cruza repos.
→ **Veredicto**: **el wedge más limpio.** Combinado con CLAIM-7: la intersección **(c)∩(d) está vacía en Rel(AI)Build** (no tiene ni self-improvement real ni cross-project). Para el paper: esta es la frase de novedad. "No concurrent system both learns from outcomes and carries those lessons across separate repositories; Rel(AI)Build explicitly laments the cross-project re-authoring problem (§1.1) without solving it."

---

### CLAIM-9 — Concesión central repetida: "developer outcomes remain future work" (Abstract, §6, §8, §9.2, §10)

*"Conformance tests on injected violations confirm each mechanism enforces its stated invariant; **developer outcomes remain future work**."* (Abstract) ...
*"They carry no information about field effectiveness or developer outcomes (§8, §9.2); we report them only to establish that each mechanism enforces its stated invariant."* (§6.2) ...
*"a full controlled study (§9.2) is required before claiming productivity outcomes"* (§7 sample-adequacy box).

→ **Qué es**: la honestidad estructural del paper. TODO lo que validan es **conformance** (¿el mecanismo hace lo que dice?), NO **effectiveness** (¿mejora al desarrollador?). El único walkthrough de outcome es N=1 (Appendix D, DRIFT vignette) y lo marcan "not a comparative evaluation".
→ **APEX**: **este es el gran igualador y nuestro mejor escudo defensivo.** Nuestra memoria (obs 18781) ya notó que "Self-Improvement Loop (Claimed Unique Pillar) Has Minimal Field Data". La tentación del reviewer será: "APEX's self-improvement loop is unvalidated". La respuesta:
>   - **El competidor más cercano en (a)+(b) está en la MISMA situación y lo pone en su abstract.** Rel(AI)Build no mide outcomes tampoco. El campo entero (H1 2026) valida conformance/prevalence, no productividad. **No es una debilidad diferencial de APEX; es el estado del campo.**
>   - APEX tiene ALGO de field data que ellos no: el skill-eval audit (WITH 60% vs WITHOUT 22%, Δ+37.5, `docs/skill-eval-audit/RESULTS.md`) es más evidencia de efecto que su N=1 vignette. **Modesta, pero existe y es más que la suya.**
→ **Veredicto**: **munición defensiva de primer orden.** En Threats-to-Validity: "Like Madatha (2026), who states that 'developer outcomes remain future work', APEX's productivity claims await a controlled study; the field's 2026 contributions validate conformance and prevalence, not outcomes. APEX nonetheless reports preliminary skill-ablation evidence (§X) absent from concurrent work." **Convierte una debilidad compartida en una ligera ventaja.**

---

## Tabla-resumen: dónde nos suple / mejora / gap suyo

| # | Claim de Madatha | ¿APEX...? | Columna | Acción en el paper |
|---|---|---|---|---|
| 1 | Tesis config-as-supply-chain | ortogonal | — | delimitar tesis, concurrent |
| 2 | 3 gaps estructurales | Gap1=**gap nuestro**, Gap2=cubierto, Gap3≠nuestro(d) | — | desambiguar Gap3; asumir Gap1 |
| 3 | SHA-256+HMAC+audit hash-chained | **gap suyo real (limpio)** | b-supply | conceder + roadmap opcional |
| 4 | Tier permissions + blocklist pre-LLM | solape, ellos más finos | **b** | dejar de reclamar (b) solo; adoptar blocklist |
| 5 | Phase-state machine determinista | **colisión frontal**, ellos más deterministas | **a** | **responder ataque LLM-judge (crítico)** |
| 6 | Compile-to-many multi-IDE | fuera de scope | — | conceder como no-objetivo |
| 7 | Jaccard drift = su "(c)" | **no es (c) real** | (b) mal etiquetada | reforzar (c) nuestro; usar su disclaimer |
| 8 | Cross-project = problema no resuelto | **(d) nuestro sin disputa** | **d** | frase de novedad (c)∩(d) |
| 9 | "developer outcomes remain future work" | **igualador defensivo** | — | Threats: debilidad compartida → ventaja |

## Los tres movimientos que este paper obliga a hacer en `main.tex`

1. **Blindar §5 contra el ataque LLM-judge (CLAIM-5).** Es el único punto donde Rel(AI)Build puede hacernos sangrar en peer review. Añadir un párrafo que deje claro que APEX combina sub-gates deterministas (git/test/OS/schema/security) *más* un juicio LLM de outcome-quality por encima — no un LLM en lugar de código. Citar su §1.2 ("non-deterministic component cannot serve as a trustworthy control") y responderlo de frente.
2. **Conceder (a) y (b) explícitamente, anclar en (a)∩(b)∩(c)∩(d).** Ya está en el plan del survey; este paper lo confirma con verbatim. Usar CLAIM-3/4/5 para conceder, CLAIM-7/8 para el wedge.
3. **Meter la concesión de outcomes de Madatha en Threats (CLAIM-9).** Convierte "APEX no valida productividad" de flanco abierto en "estado del campo, y nosotros tenemos algo de ablation que ellos no".

## Dos apropiaciones baratas (opcional, refuerzan APEX sin cambiar la tesis)

- **Blocklist de comandos derivada de incidentes (Tabla 4)**: `curl|bash`, `git config --global/--system`, `core.hooksPath`, `detached-spawn`, persistence paths (cron/systemd/XDG). Portable directo a un template DevOps de APEX. Encaja con el Sprint 19 (gitleaks). Cierra parte del flanco (b).
- **Content-addressing de skill/proposal artifacts (Gap 1)**: recomputar-y-abortar SHA sobre lo que `skill_forge`/`library_ingest` escriben. Barato, cierra el flanco supply-chain antes de que un reviewer lo abra. Anotarlo como sprint, no bloqueante para la submission.

---

*Fin de la lectura acompañada. Fuente: relaibuild.pdf leído 42/42 pág, 12 jul 2026. Todas las citas verbatim del PDF.*
