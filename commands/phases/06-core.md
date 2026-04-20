# Fase 6 — Core (dominio)

Implementar la logica de negocio pura, sin dependencias externas.

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
- **[6e]** Verificar que todo compila y los imports son correctos.
- **[6f]** Registrar cada componente con `apex_add_component`.
- **[6g]** `apex_set_phase(phase_number=6, status="completed")`.

## Reglas de oro (SMA)

1. Un agente, una responsabilidad.
2. El orquestador NUNCA procesa. Coordina y delega.
3. Fallar con elegancia. Cada agente debe tener salida de degradacion.
4. Evaluar antes de desplegar. Sin benchmark no hay SMA, solo esperanza.
5. RAG cuando el conocimiento cambia. Dominio estatico → parametrizar.
   Dinamico → vectorizar.

## Criterio de salida

- Entidades + ports + use cases + agents implementados.
- Build limpio.
- Cada componente registrado en context.db.
- Fase marcada como `completed` en context.db.
