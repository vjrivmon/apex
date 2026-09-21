# Consensus Deep Search — matices y papers nuevos (11 jul 2026)

> Los "Deep Search reports" de Consensus (con evidence-strength, screening flow, timeline)
> son más ricos que los CSVs de títulos. Aquí registro (1) el veredicto matizado de cada
> query — clave para escribir related-work honesto —, (2) los papers ancla que Consensus ya
> identificó, y (3) **papers NUEVOS que no estaban en los CSVs** y son directamente relevantes.
> Los dos hallazgos marcados 🔴 son potenciales VECINOS de APEX, no solo fundamento.

---

## 🔴 Hallazgos que cambian el posicionamiento (posibles vecinos, no fundamento)

Estos dos aparecieron en el Deep Search de "quality gates" y están peligrosamente cerca de
los ejes de novedad de APEX. Encolados al workflow de competidores para deep-read.

- **Zhang, D. (2026). AgentDevel: Reframing Self-Evolving LLM Agents as Release Engineering.**
  arXiv 2601.04620. — Reencuadra agentes auto-evolutivos como release engineering. Toca el
  eje self-improvement loop **y** el de gates a la vez. **Verificar overlap con grader/doctor/skill-forge.**
- **Maiorano, A. C. (2026). Automated Self-Testing as a Quality Gate: Evidence-Driven Release
  Management for LLM Applications.** arXiv 2603.15676. — "Quality gate" + "LLM applications"
  en el título. Cerca del gate 10.5 / grader. **Verificar si es un gate determinista bloqueante
  o solo self-testing. Diferencia clave: APEX bloquea en PreToolUse antes del juicio LLM.**

---

## Query — Quality gates reducen defectos (Deep Search, 50 papers)

**Veredicto:** qualified yes — reducen defectos **cuando se aplican con automatización,
enforcement y de forma selectiva/basada en riesgo**; no todo diseño de gate funciona igual.

**Papers ancla nuevos (no estaban en el CSV):**
- **Mockus et al. (2025), Leveraging Risk Models... Code Un-Freeze at Scale** (TOSEM,
  10.1145/3722216) — **el dato estrella**: gating basado en riesgo en Meta → **52% menos
  outages** gateando solo el 16% de cambios, +42% de cambios landeados. Ancla que un gate
  **selectivo** (como el de APEX, que no bloquea todo sino transiciones de fase críticas)
  mejora calidad sin matar throughput. Cita industrial fuerte y reciente.
- **Altunel & Say (2021), Software Product System Model** (SN CS, 10.1007/s42979-021-00899-9)
  — caso DevOps 2 años: **-69.5% vulnerabilidades**, +29.4% cobertura con gates dinámicos.
- **Trautsch (2024), Usefulness of Automatic Static Analysis Tools** — **contraevidencia útil**:
  gates de solo-análisis-estático tienen efecto pequeño. Justifica que APEX combine
  determinista + LLM-judge + review, no una sola señal.
- **Bianchi et al. (2020), Agile, Stage-Gate and their combination** (ya en CSV) — Stage-Gate
  rígido correlaciona negativo con velocidad/coste. Ancla el diseño híbrido de APEX.

**Cómo citar:** el argumento money es "gates selectivos basados en riesgo reducen defectos
sin friccionar todo" (Mockus 2025) + "omitir/bypasear gates erosiona la calidad" (Ghanbari
2018, Ojala 2010) → por eso APEX los hace **bloqueantes y verificados**, no voluntarios.

---

## Query — LLM-as-judge coincide con evaluadores humanos 🔑 (blindaje del grader)

**Veredicto:** qualified yes — modelos fuertes alcanzan acuerdo tipo-humano en tareas con
rúbricas claras, pero el acuerdo **varía mucho** por dominio y NO deben tratarse como
reemplazo universal sin calibración/grounding/supervisión.

**Este es el eje que más blinda tu grader ante un revisor hostil. Papers clave:**
- **Zheng et al. (2023), Judging LLM-as-a-judge with MT-Bench and Chatbot Arena**
  (arXiv 2306.05685) — la cita canónica: GPT-4 juez >80% acuerdo con humanos, ~= acuerdo
  humano-humano. Fundamento de que un LLM-judge es viable.
- **Wang et al. (2025), Can LLMs Replace Human Evaluators? LLM-as-a-Judge in Software
  Engineering** (Proc. ACM SE, 10.1145/3728963) — **el más relevante para APEX**: correlaciones
  near-human en tareas de código (Pearson 81.3 code translation, 68.5 code generation). Ancla
  directamente que el grader de APEX (juez sobre output de código) es defendible.
- **Bavaresco et al. (2024), LLMs instead of Human Judges? 20 NLP tasks** (arXiv 2406.18403)
  — el matiz honesto: varianza sustancial entre tareas. Justifica que el grader de APEX use
  **checks deterministas primero** y el LLM-judge solo donde hay rúbrica.
- **Tan et al. (2024), JudgeBench** (arXiv 2410.12784) — en pares correctness-based difíciles,
  muchos jueces apenas superan el azar. **Contraevidencia crítica**: por eso APEX NO confía
  solo en el LLM-judge — el gate determinista corre antes.
- **Jung et al. (2024), Trust or Escalate: LLM Judges with Provable Guarantees** (arXiv
  2407.18370) — framework selectivo/híbrido: garantiza nivel de acuerdo humano con escalado.
  **Análogo conceptual del diseño de APEX** (determinista → LLM-judge → humano). Cita puente.
- Thakur et al. (2024), Judging the Judges — sesgos/vulnerabilidades de LLM-judges.

**Cómo citar:** "LLM-judges coinciden con humanos en código con rúbrica clara (Wang 2025,
Zheng 2023), pero fallan en correctness difícil (Tan 2024) → APEX corre checks deterministas
ANTES del juicio LLM (Jung 2024 valida el patrón híbrido)". Esto convierte una debilidad
potencial del reviewer en una decisión de diseño justificada.

---

## Query — RAG reduce alucinación (fundamento del context substrate / second brain)

**Veredicto:** qualified yes — reduce alucinación por grounding en evidencia externa, pero
NO la elimina; falla cuando el retrieval falla o el generador ignora la evidencia.

**Papers ancla:**
- **Gao et al. (2023), RAG for LLMs: A Survey** (arXiv 2312.10997) — survey de referencia.
- **Huang et al. (2023), A Survey on Hallucination in LLMs** (ACM TOIS, 10.1145/3703155) —
  taxonomía de alucinación; RAG como mitigación por knowledge-gap.
- **Chen et al. (2023), Benchmarking LLMs in RAG** (arXiv 2309.01431) — modos de fallo:
  negative rejection, integración, info falsa recuperada.
- **Wu et al. (2023), RAGTruth** (arXiv 2401.00396) — corpus de alucinación en RAG; los
  outputs pueden contradecir los docs recuperados → por eso APEX **verifica contra fuentes**.

**Cómo citar:** ancla el context substrate + hybrid retrieval de APEX como grounding, pero
con el matiz honesto (RAGTruth, Chen 2023) de que el retrieval debe ser bueno — que es por lo
que APEX usa temporal facts + FTS5 + error memory, no un blob RAG plano.

---

## Query — Documentación estructurada de decisiones mejora mantenibilidad (wiki/decisions/, ADRs)

**Veredicto:** clear yes con caveats de implementación — preserva el "por qué", mejora
comprensión/trazabilidad/alineación; la evidencia de *velocidad* de mantenimiento es más fina
que la de *comprensión*.

**Papers ancla (varios nuevos vs CSV):**
- **Buchgeher et al. (2023), Using ADRs in Open Source Projects — MSR/GitHub** (IEEE Access,
  10.1109/access.2023.3287654) — Q1: adopción real y baja (la mitad de repos con ADRs tienen
  solo 1-5 records). **Justifica que APEX AUTOMATICE la captura** — el problema es el coste de
  captura manual.
- **Gacitúa et al. (2026), ADR-E Framework** (IEEE Access) — **-30% MTTR** en 2 casos
  industriales con ADRs explicables. Dato citable directo.
- **Conklin (1989), Design rationale and maintainability** — seminal.
- **Theunissen et al. (2023)** — la doc funciona mejor **cerca del código** (PRs, repo local),
  no en herramientas separadas. **Ancla que wiki/decisions/ viva en el repo**, no en un wiki
  externo.
- 🔴 **Su et al. (2026), Evaluating LLMs for Detecting Architectural Decision Violations**
  (arXiv 2602.07609) — LLMs que detectan violaciones de decisiones documentadas. **Cerca del
  grader de APEX** (que verifica que el código honra las decisiones). Verificar overlap.
- **Dorado & Hurtado (2019)** — caveat honesto: mejora comprensión pero no siempre tiempo de
  mantenimiento. Citar como matiz.

**Cómo citar:** "documentar decisiones mejora mantenibilidad (de Souza 2005, Conklin 1989,
Gacitúa 2026), pero la adopción manual es baja (Buchgeher 2023) → APEX automatiza la captura
y la guarda junto al código (Theunissen 2023)".

---

## Query — Checklists mejoran compliance en tareas complejas (checklists de fase, security L1-L8)

**Veredicto:** qualified yes — mejoran compliance medido, pero las ganancias dependen de
diseño e implementación; el tick-box puede subir compliance nominal sin mejorar ejecución.

**Papers ancla:**
- **Habtie et al. (2025), Beyond compliance: WHO Surgical Safety Checklist** (meta-analysis
  Q1) — compliance global 73%, completitud 51%. Evidencia fuerte y reciente de la analogía canónica.
- **De Bie et al. (2020), Intelligent checklists in the ICU** — checklist **digital dinámico**
  subió completitud 75→100% vs papel. **Ancla el checklist embebido/verificado de APEX** vs
  uno estático.
- **Clay-Williams & Colligan (2015)** — cita puente aviación↔healthcare↔sistemas complejos.
- **Catchpole & Russ (2015) / Paterson et al. (2023) / Grigg (2015 checklist fatigue)** —
  matices críticos: tick-box, fatiga. **Justifican que APEX los haga bloqueantes+verificados
  por el grader**, no voluntarios, y acotados por fase (no monolíticos).
- **Verdaasdonk et al. (2009) / Thomassen et al. (2011)** — diseño: cortos, workflow-matched,
  ownership local → mejor adopción.

---

## Query — Checklists de seguridad reducen vulnerabilidades (security gate AgentArmor concretamente)

**Veredicto:** qualified yes pero **limitado y context-dependent** — el hallazgo más
incómodo/honesto de toda la cosecha, y hay que citarlo bien.

**Papers clave:**
- **Braz et al. (2022), Less is More: Supporting Developers in Vulnerability Detection during
  Code Review** (ICSE, 10.1145/3510003.3511560) — **hallazgo fuerte y contraintuitivo**:
  pedir a los reviewers que **se enfoquen en seguridad** multiplicó ×8 la detección, pero
  **añadir un checklist a medida NO mejoró más**. Un "security mindset prompt" simple funciona
  mejor que un checklist complejo. **APEX debe posicionar su security gate con cuidado**: el
  valor no es el checklist per se, sino forzar la *atención* a seguridad en una fase dedicada
  (fase 10 + gate 10.5) — que es exactamente lo que hace.
- **Zahan et al. (2022/2023), Do Software Security Practices Yield Fewer Vulnerabilities?**
  (ICSE-SEIP, 10.1109/icse-seip58684.2023.00032) — prácticas de seguridad formalizadas ↓ riesgo.
- **Teng et al. (2021), Checklist Usage in Secure Software Development** — checklists ayudan al
  descomponer tareas complejas; fallan si son abstractos o crean falsa sensación de seguridad.
- **Charoenwet et al. (2023), Secure code reviews empirical study** (EMSE) — debilidades de
  código relacionadas con seguridad en reviews.

**Cómo citar (con honestidad intelectual):** "los checklists de seguridad como *lista* tienen
efecto mixto (Braz 2022); lo que sí funciona es forzar atención dedicada a seguridad (Braz
2022 ×8) → APEX no vende el checklist, vende una **fase de seguridad obligatoria y bloqueante**
(gate 10.5) que garantiza que esa atención ocurre". Esto es más defendible que "APEX tiene
checklists de seguridad".

---

## Papers NUEVOS a valorar para references.bib (no estaban en los CSVs ni en la bib actual)

| Paper | Año | arXiv/DOI | Eje | Prioridad |
|---|---|---|---|---|
| Mockus et al., Risk Models for Code Un-Freeze at Scale (Meta) | 2025 | 10.1145/3722216 | Gates selectivos | ALTA (dato 52%) |
| Zheng et al., Judging LLM-as-a-judge (MT-Bench) | 2023 | 2306.05685 | Grader | ALTA |
| Wang et al., LLM-as-a-Judge in Software Engineering | 2025 | 10.1145/3728963 | Grader | ALTA (código) |
| Tan et al., JudgeBench | 2024 | 2410.12784 | Grader (caveat) | ALTA |
| Jung et al., Trust or Escalate | 2024 | 2407.18370 | Grader híbrido | MEDIA |
| Braz et al., Less is More (sec code review) | 2022 | 10.1145/3510003.3511560 | Security gate | ALTA |
| Gao et al., RAG for LLMs: A Survey | 2023 | 2312.10997 | Context substrate | MEDIA |
| Wu et al., RAGTruth | 2023 | 2401.00396 | Context (caveat) | MEDIA |
| Buchgeher et al., ADRs in OSS (MSR) | 2023 | 10.1109/access.2023.3287654 | wiki/decisions | MEDIA |
| Gacitúa et al., ADR-E (30% MTTR) | 2026 | IEEE Access | wiki/decisions | MEDIA |
| 🔴 Zhang, AgentDevel (self-evolving = release eng) | 2026 | 2601.04620 | VECINO | verificar |
| 🔴 Maiorano, Self-Testing as Quality Gate for LLM apps | 2026 | 2603.15676 | VECINO | verificar |
| 🔴 Su et al., LLMs Detecting Arch Decision Violations | 2026 | 2602.07609 | VECINO (grader) | verificar |

Los 🔴 pasan al workflow de competidores. El resto son fundamento sólido revisado por pares.
