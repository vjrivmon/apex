---
name: prototype
description: Prototipa lógica de negocio compleja como máquina de estados ejecutable (TUI Python con Textual). Mejor que prosa para validar transiciones, edge cases y reglas de negocio. Genera un .py corriendo + diagrama Mermaid commiteado a wiki/concepts/. Triggers ES/EN — prototipo, prototype, máquina de estados, state machine, valida transiciones, business logic complejo, "más de 5 reglas".
---

<what-to-do>

Cuando la lógica de un feature pase de prosa a estados con transiciones, deja de escribir más párrafos y construye un prototipo ejecutable. Una TUI con bindings por evento permite "atajar" a un estado profundo en dos teclas y ver al instante qué reglas saltan, qué guards bloquean y qué estados quedaron muertos. La prosa miente con elegancia; la máquina ejecutable falla en voz alta.

Los pasos van en este orden:

1. Lista los **estados** (sin verbos, solo sustantivos: `draft`, `review`, `paid`).
2. Lista las **transiciones** como tuplas `{from, event, to, guard?}` — una por cada arista del grafo.
3. Marca el `initial_state`.
4. Llama a `apex_prototype_init(feature_name, states, transitions, initial_state)`.
5. Abre el TUI generado (`pip install textual && python .apex/prototypes/<feature>.py`) y recorre cada binding hasta convencerte de que cubre el dominio.
6. Cuando descubras un estado o regla que faltaba, edita estados/transiciones y vuelve a llamar `apex_prototype_init(..., force=True)` — la idempotencia y el `state_machines.UNIQUE` te respaldan.
7. Sincroniza el archivo `wiki/concepts/<feature>-state-machine.md` (ya commiteado por el tool) con cualquier nota de diseño que surja del prototipo.

</what-to-do>

<when-to-invoke>

Cuatro disparadores concretos. Si encajas en alguno, llama al tool sin más debate:

- **Spec con >5 reglas de negocio**. Cada regla es una transición potencial. Modélala antes de escribirla en prosa.
- **Decision (`wiki/decisions/`) con `complexity_score` alta y solo prosa**. Si el rationale ocupa más de 30 líneas y describe estados, conviértelo en máquina.
- **Tests fallando que apuntan a transiciones mal entendidas**. El prototipo te deja recorrer manualmente la cadena que el test ya prueba; verás dónde diverge tu mental model del código real.
- **El Advisor emite `recommend_skill_handoff(target='prototype')`**. Acéptalo: el bundle ya incluye la evidencia (decision X, tests fallando, etc.). Inicia con `apex_handoff_skill(from_skill=<skill_actual>, to_skill='prototype', reason=<motivo>, snapshot={...})` para no perder el contexto previo.

</when-to-invoke>

<anti-patrones>

- **Prototipar cuando la lógica cabe en 3 reglas.** Para if/elif/else trivial, escribe el código y un test. La máquina añade ceremonia sin valor.
- **No validar reachability.** Un estado al que nadie llega es código muerto disfrazado. `apex_prototype_init` ya falla si detecta uno; no lo desactives.
- **Omitir guards.** Si una transición depende de una condición (`has_required_fields`, `payment_authorized`), nómbrala en el campo `guard`. La prosa tiene huecos; los guards son contractuales.
- **Saltarse el wiki/concepts/.** El TUI sin el diagrama Mermaid es un binario opaco; el diagrama sin el TUI es un dibujo bonito. APEX exige los dos para que el grader (fase 9) pueda verificar que el código real honra las transiciones del prototipo.
- **Usar `force=True` por defecto.** Si chocas con un `feature_name` ya existente, lee el archivo previo: probablemente otra rama ya modeló esta lógica. Sobrescribir sin entender pierde diseño.

</anti-patrones>

<puente-apex>

- El **Advisor** (S15) emite `recommend_skill_handoff(target='prototype')` cuando ve un Decision denso sin prototipo asociado. Acepta o dismissea con razón explícita — los dismiss recurrentes alimentan al doctor (A7 futuro).
- El **grader** (fase 9) lee la tabla `state_machines` y, dada la implementación real, comprueba que cada `transition` declarada existe como camino en el código (test o fragmento que la dispara). Transiciones no honradas = deuda; transiciones extra = añade al prototipo o elimina del código.
- Las decisiones tomadas durante el prototipo van a `wiki/decisions/YYYY-MM-DD-<feature>-state-machine.md` con `apex_add_decision`. El prototipo es la evidencia ejecutable; el ADR es la justificación de por qué esa máquina y no otra.
- Si el prototipo se usa dentro de un flujo Pocock (grill-with-docs → prototype → grill-with-docs), envuélvelo en `apex_handoff_skill` para que el cierre llame a `apex_resume_skill_handoff(handoff_id, result_summary='estado X validado, regla Y descartada')`. Sin handoff, el Advisor lo marcará como huérfano a los 30 min.

</puente-apex>

<deuda-explicita>

S15 entrega scaffold + diagrama + INSERT. NO entrega:

- Replay de transiciones desde un seed (deja el TUI manual por ahora).
- Fuzzing de guards (lo añade S16 con propiedades estilo Hypothesis).
- Atajos a estados profundos vía secuencia tecleada (S16: `goto cart>shipping>paid` con un comando).
- Promoción automática de la máquina a tests parametrizados (S16+).

Si necesitas algo de lo anterior, abre la limitación en una decision con `apex_add_decision(rationale='S15 prototype scaffold-only; lo extiendo a mano hasta S16')`.

</deuda-explicita>
