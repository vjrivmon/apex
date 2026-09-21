# Fundamento empírico atemporal para el paper APEX (Consensus)

> Selección de los papers más citables de 4 queries de Consensus (11 jul 2026), por eje
> de diseño de APEX. Estos NO son competidores de APEX; son la base empírica revisada por
> pares que respalda *por qué* un proceso disciplinado (gates, TDD, checklists, ADRs) mejora
> el desarrollo. Todos los DOIs y títulos provienen de los CSVs exportados; nada inventado.

## Query 1 — ¿Reducen defectos los quality gates? (eje: gate 10.5 + fases con grader bloqueante)

| Título | Año | Tipo | Q | Citas | DOI |
|---|---|---|---|---|---|
| Advances in software inspections (Fagan) | 1986 | Literature review | Q1 | 767 | 10.1109/tse.1986.6312976 |
| Effects of Process Maturity on Quality, Cycle Time, and Effort | 2000 | Cross-sectional | Q1 | 539 | 10.1287/mnsc.46.4.451.12056 |
| Continuous Integration, Delivery and Deployment: A Systematic Review | 2017 | Systematic review | Q1 | 619 | 10.1109/access.2017.2685629 |
| DevOps and software quality: A systematic mapping | 2020 | Literature review | Q1 | 144 | 10.1016/j.cosrev.2020.100308 |
| Agile, Stage-Gate and their combination | 2020 | Cross-sectional | Q1 | 127 | 10.1016/j.jbusres.2018.05.003 |
| Omission of Quality Software Development Practices | 2018 | Systematic review | Q1 | 32 | 10.1145/3177746 |

- **Fagan (1986)** — cita canónica: gate de inspección formal antes de avanzar reduce defectos y coste. Ancla gate 10.5 + gates de fase.
- **Harter et al. (2000)** — Q1 (Management Science): mayor madurez de proceso → mejor calidad, menos rework. Tesis central de APEX.
- **Shahin et al. (2017)** — SR Q1 (619 citas): prácticas continuas y gates automatizados. Ancla scaffold DevOps (fase 11).
- **DevOps & software quality (2020)** — systematic mapping Q1: entrega ↔ calidad medible.
- **Cooper & Sommer (2020)** — matiz: Stage-Gate puro penaliza velocidad, pero híbrido con ágil mejora. Ancla diseño híbrido de APEX (gates + iteración).
- **Omission of Quality Practices (2018)** — SR Q1: omitir prácticas → inefectividad. Justifica gates **bloqueantes**, no opcionales.

## Query 2 — ¿Reduce defectos el TDD? (eje: skill `tdd`, fase 4 edge-cases, fase 9 QA ≥80%)

| Título | Año | Tipo | Q | Citas | DOI |
|---|---|---|---|---|---|
| Realizing quality improvement through TDD (Nagappan) | 2008 | Case study | Q1 | 165 | 10.1007/s10664-008-9062-z |
| A family of experiments on test-driven development | 2020 | Meta-analysis | Q1 | 30 | 10.1007/s10664-020-09895-8 |
| TDD as a defect-reduction practice (Williams) | 2003 | Case study | — | 230 | 10.1109/issre.2003.1251029 |
| Assessing TDD at IBM (Maximilien & Williams) | 2003 | Case study | — | 260 | 10.1109/icse.2003.1201238 |
| TDD with mutation testing – experimental study | 2020 | Non-randomized exp | Q1 | 10 | 10.1007/s11219-020-09534-x |
| Test Driven Development: By Example (Beck) | 2002 | Libro | — | 2153 | — |

- **Nagappan et al. (2008)** — industrial Q1: TDD reduce defectos pre-release 15-35% a cambio de más tiempo. Cita empírica más limpia para skill `tdd`.
- **Santos et al. (2020)** — **meta-analysis Q1**: efecto positivo pero context-dependent. Ancla TDD como skill contextual, no dogma.
- **Williams et al. (2003)** — ~40% menos defectos sin penalizar productividad.
- **Maximilien & Williams (2003)** — replica el efecto en sistema no trivial a tiempo.
- **Roman & Mnich (2020)** — mutation testing en bucle TDD detecta más defectos. Ancla cobertura ≥80% (fase 9).
- **Beck (2002)** — fuente seminal (libro). Referencia fundacional, no evidencia.

> **FLAG contraevidencia (citar como matiz, no como apoyo):** Wilkerson et al. (2012),
> *Comparing the Defect Reduction Benefits of Code Inspection and TDD* (Q1, 49 citas):
> la inspección de código supera a TDD; TDD no supera a la programación tradicional.

## Query 3 — ¿Mejoran los checklists el compliance en tareas complejas? (eje: checklists de fase, security-audit L1-L8)

| Título | Año | Tipo | Q | Citas | DOI |
|---|---|---|---|---|---|
| Systematic Review of Effectiveness/Compliance of Safety Checklists (Borchard) | 2012 | Systematic review | Q1 | 308 | 10.1097/sla.0b013e3182682f27 |
| Back to basics: checklists in aviation and healthcare | 2015 | Literature review | Q1 | 182 | 10.1136/bmjqs-2015-003957 |
| Requirements for design/implementation of checklists for surgical processes | 2009 | Systematic review | Q1 | 136 | 10.1007/s00464-008-0044-4 |
| Implementation of checklists... high-reliability organisations | 2011 | Interview study | Q1 | 140 | 10.1186/1757-7241-19-53 |
| The problem with checklists | 2015 | Commentary | Q1 | 150 | 10.1136/bmjqs-2015-004431 |
| Beyond compliance: WHO Surgical Safety Checklist | 2025 | Meta-analysis | Q1 | 0 | 10.1186/s12913-025-12569-0 |

- **Borchard et al. (2012)** — SR Q1 (308 citas): checklists de seguridad → menos mortalidad con buen compliance. Analogía canónica "checklist obligatorio → cumplimiento".
- **Clay-Williams & Colligan (2015)** — cita puente: transfiere lógica de aviación a sistemas complejos. Conecta APEX con tradición aviación/cirugía.
- **Verdaasdonk et al. (2009)** — qué hace que un checklist funcione. Ancla diseño de templates L1-L8.
- **Thomassen et al. (2011)** — checklists cortos y centrados en el usuario → mejor adopción. Justifica checklists acotados por fase.
- **Catchpole & Russ (2015)** — matiz crítico: no son bala de plata; dependen de la implementación. Justifica gates **bloqueantes y verificados**.
- **Habtie et al. (2025)** — meta-analysis Q1 reciente del checklist WHO/Haynes.

## Query 4 — ¿Mejora la mantenibilidad la documentación estructurada de decisiones? (eje: `wiki/decisions/`, ADRs, grill-with-docs)

| Título | Año | Tipo | Q | Citas | DOI |
|---|---|---|---|---|---|
| A study of the documentation essential to software maintenance | 2005 | Empírico | — | 229 | 10.1145/1085313.1085331 |
| Design rationale and maintainability (Conklin) | 1989 | — | — | 74 | 10.1109/hicss.1989.48049 |
| Using ADRs in Open Source Projects (MSR/GitHub) | 2023 | Cross-sectional | Q1 | 10 | 10.1109/access.2023.3287654 |
| Explainability in Software Architectural Decisions (ADR-E) | 2026 | Empírico | Q1 | 1 | 10.1109/access.2025.3648573 |
| Traceability of Architectural Design Decisions: Systematic Mapping | 2023 | Literature review | Q3 | 2 | 10.2478/fcds-2023-0018 |
| ADRs in Practice: Action Research | 2024 | Action research | — | 1 | 10.1007/978-3-031-70797-1_22 |

- **de Souza et al. (2005)** — 229 citas: qué artefactos usan los mantenedores (incluye decisiones). Ancla `wiki/decisions/`.
- **Conklin (1989)** — seminal: capturar rationale durante el desarrollo baja coste de mantenimiento.
- **Buchgeher et al. (2023)** — Q1, MSR sobre GitHub: adopción real (y baja) de ADRs. Justifica que APEX **automatice** su creación.
- **Gacitúa et al. (2026)** — Q1: framework estructurado mejora trazabilidad y MTTR. Cita reciente y directa.
- **Hyun & Hurtado (2023)** — Q3: falta de trazabilidad → rework. Ancla el problema (cuartil bajo, prioridad menor).
- **Ahmeti et al. (2024)** — action research: ADRs mejoran transferencia de conocimiento.

> Nota: este CSV es el más flojo en evidencia dura. Los de más peso: de Souza (229 citas) y Buchgeher (Q1 MSR).

## Top 6 imprescindibles (a `references.bib`)

| # | Título | Año | Tipo | Q | Citas | DOI | Eje |
|---|---|---|---|---|---|---|---|
| 1 | Effects of Process Maturity on Quality... | 2000 | Cross-sectional | Q1 | 539 | 10.1287/mnsc.46.4.451.12056 | Proceso/gates |
| 2 | Advances in software inspections (Fagan) | 1986 | Lit. review | Q1 | 767 | 10.1109/tse.1986.6312976 | Gate pre-avance |
| 3 | A family of experiments on TDD | 2020 | Meta-analysis | Q1 | 30 | 10.1007/s10664-020-09895-8 | Skill `tdd` |
| 4 | Realizing quality improvement through TDD | 2008 | Case study | Q1 | 165 | 10.1007/s10664-008-9062-z | Skill `tdd` (15-35%) |
| 5 | SR of Safety Checklists in surgery (Borchard) | 2012 | Systematic review | Q1 | 308 | 10.1097/sla.0b013e3182682f27 | Checklists/security gate |
| 6 | Documentation essential to software maintenance | 2005 | Empírico | — | 229 | 10.1145/1085313.1085331 | `wiki/decisions/` |

**Suplentes:** Clay-Williams (2015, cita-puente Gawande) · Buchgeher ADRs (2023, Q1).

**Contraevidencia a citar como matiz honesto:** Wilkerson et al. (2012, inspección > TDD) · Catchpole & Russ (2015, límites de checklists).
