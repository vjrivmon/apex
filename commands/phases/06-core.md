# Fase 6 — Core (dominio)

Implementar la logica de negocio pura, sin dependencias externas. **Tests
unitarios obligatorios para cerrar fase** (lección focusnow#3: nada de
cáscara declarada completa).

Siempre arquitectura hexagonal + SMA cuando haya lógica distribuida.
Nunca colapsar responsabilidades en un módulo gigante, incluso cuando parezca
más simple.

## Sub-pasos en orden

- **[6a]** Entidades de dominio (modelos, value objects, enums).
- **[6b]** Puertos/interfaces (repositorios, servicios externos). Un puerto
  por cada adaptador previsto.
- **[6c]** Casos de uso / application services.
- **[6d]** Agentes si es un SMA: orquestador (NUNCA procesa, solo coordina),
  workers especializados (una responsabilidad cada uno), pipeline de
  comunicacion. Si no puedes describir un agente en una frase, son dos.
- **[6e]** **Tests unitarios OBLIGATORIOS** para entidades + casos de uso
  principales. Mínimo 1 test por entidad y 1 test por caso de uso. El
  grader bloquea el cierre si `len(test_files) == 0`. Apuntar a coverage
  de domain ≥ 80% en fase 9 — aquí basta con el esqueleto verde.
- **[6f]** Verificar que todo compila y los tests pasan
  (`pytest -q` / `npm test`).
- **[6g]** Registrar cada componente con `apex_add_component`.
- **[6h]** Conventional commit del core (`feat: core domain + ports +
  use_cases + tests unitarios`).
- **[6i]** Ejecutar `apex_grader_evaluate(phase=6, mode="full")`.
  Checks: `git_initialized` (de fase 5), `tests_present` (NUEVO),
  `os_detected`. El modo `full` invoca al juez LLM si hay
  `ANTHROPIC_API_KEY` para detectar mock/cáscara.
- **[6j]** Si verdict pasa: `apex_set_phase(phase_number=6,
  status="completed")`.

## Reglas de oro (SMA)

1. Un agente, una responsabilidad.
2. El orquestador NUNCA procesa. Coordina y delega.
3. Fallar con elegancia. Cada agente debe tener salida de degradacion.
4. Evaluar antes de desplegar. Sin benchmark no hay SMA, solo esperanza.
5. RAG cuando el conocimiento cambia. Dominio estatico → parametrizar.
   Dinamico → vectorizar.

## Skills recomendadas

- **`tdd`** (Sprint 14) — el bucle red-green-refactor es el "como" de
  esta fase. Una rebanada vertical cada vez (un test → una
  implementacion), nunca rebanado horizontal (todos los tests primero).
  Usa el vocabulario canonico de `wiki/entities/concepts/` para nombrar
  tests e interfaces. Tests de integracion sobre interfaces publicas,
  no mocks de internos.

## Criterio de salida (outcome-based)

- Entidades + ports + use cases + agents implementados.
- Build limpio + tests unit pasando.
- Cada componente registrado en context.db.
- Verdict del grader: `should_block=false`, `quality ≥ 3`.
- Fase marcada como `completed` (sólo si verdict pasa).
