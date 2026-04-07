# /apex — Diseña un Sistema Multi-Agente directamente desde Claude Code

## Descripción

Modo directo de APEX: el usuario describe su idea a Claude Code y este actúa
como la interfaz conversacional de APEX. Sin navegador, sin web UI — Claude Code
ES el cerebro.

## Instrucciones

Cuando el usuario invoque `/apex` o describa una idea para un sistema
multi-agente, sigue este flujo:

### Fase 1: Smart Assessment

Analiza la idea del usuario. Decide:

- **¿Es suficientemente completa?** (tiene: problema claro, usuarios, contexto,
  complejidad estimada)
  - **SÍ** → Salta a Fase 3 (genera SPEC directo)
  - **NO** → Ve a Fase 2 (entrevista por rondas)

### Fase 2: Entrevista por Rondas (con opciones)

Usa `AskUserQuestion` para hacer preguntas estructuradas con opciones
clickeables. Máximo 5-7 rondas. Cada ronda:

1. Consulta el RAG de APEX (ChromaDB en 100.88.164.20:8000) para enriquecer las
   opciones con patrones y casos reales
2. Presenta la pregunta con 3-4 opciones relevantes
3. El usuario elige o escribe su propia respuesta

Rondas típicas:

- **Ronda 1**: Tipo de problema (análisis, automatización, monitoreo,
  generación, otro)
- **Ronda 2**: ¿Subtareas secuenciales o paralelas? (Pipeline,
  Orquestador-Worker, Mixto)
- **Ronda 3**: ¿Necesita RAG? ¿Memoria entre sesiones? ¿Herramientas externas?
- **Ronda 4**: Stack tecnológico preferido
- **Ronda 5**: Restricciones (presupuesto, latencia, privacidad, offline)
- **Ronda 6**: Confirmación del alcance

### Fase 3: Generación de SPEC.md

Genera un SPEC.md completo en el directorio del nuevo proyecto con:

- Problema y visión
- Usuarios objetivo
- Funcionalidades core
- Stack tecnológico
- Arquitectura SMA propuesta (patrón + agentes + justificación)
- Métricas de éxito

### Fase 4: Diseño de Arquitectura

Presenta la arquitectura con:

- Patrón seleccionado del árbol de decisión
- Diagrama ASCII de los agentes
- Especificación de cada agente (nombre, responsabilidad, modelo, RAG, memoria,
  modo fallo)
- Justificación con referencia a papers o casos reales de Vicente
- Pide aprobación explícita antes de continuar

### Fase 5: Generación de Código

Genera el proyecto completo con arquitectura hexagonal:

```
proyecto/
├── core/
│   ├── domain/      # Entidades del dominio
│   ├── agents/      # Agentes del SMA
│   └── ports/       # Interfaces
├── infrastructure/  # Adaptadores (Ollama, ChromaDB, etc.)
├── application/     # API (FastAPI) + use cases
└── shared/          # Config, errores
```

### Fase 6: Review + Export

- Revisa el código generado (seguridad, calidad, arquitectura)
- Genera skills de Claude Code si aplica
- Crea el directorio en ~/RoadToDevOps/
- Inicializa git

## Árbol de Decisión para Arquitectura

```
¿Hay tarea principal con subtareas especializadas?
├── SÍ: ¿Subtareas secuenciales o paralelas?
│   ├── Secuenciales → PIPELINE
│   └── Paralelas → ORQUESTADOR-WORKER
└── NO: ¿Decisiones por consenso/votación?
    ├── SÍ → CONSENSO
    └── NO: ¿Especialistas que se consultan entre sí?
        ├── SÍ → RED DE EXPERTOS
        └── NO: ¿Sistema reactivo a eventos?
            ├── SÍ → REACTOR
            └── NO: ¿Mejora iterativa?
                ├── SÍ → REFLEXIÓN
                └── NO → AGENTE ÚNICO (no es SMA)
HÍBRIDO: combina 2+ patrones si el problema lo requiere
```

## Reglas de Oro

1. Un agente, una responsabilidad. Si no lo describes en una frase, son dos.
2. El orquestador NUNCA procesa. Coordina y delega.
3. Fail gracefully. Todo agente debe tener output de degradación.
4. Evalúa antes de desplegar. Sin benchmark, no hay SMA, hay esperanza.
5. RAG cuando el conocimiento cambia. Dominio estático → parametriza. Dinámico →
   vectoriza.

## RAG Context

Consulta ChromaDB (100.88.164.20:8000) para:

- `sma_patterns`: 7 patrones de arquitectura SMA
- `real_cases`: 21 casos reales de proyectos de Vicente

## Casos Reales de Referencia (para justificaciones)

- claude-007-agents: 68 agentes, 4 niveles jerárquicos
- FeedbackIA: 10 agentes, A/B testing, hexagonal
- Meridian: IDE con 13 fases autónomas
- Catan Coach: RAG dual + 7 agentes + genético
- Catan Advisor API: Visión IA + 93 parámetros genéticos
- AgentForge: SMA que diseña SMAs (dogfooding)
- Tutor Ohm: Benchmark de 6+ LLMs, detección de concepciones erróneas
- Smart Agent Workflow MCP: Test gates + knowledge graph
- Career Ops: Pipeline de 45+ portales
- Osyris: Gestión scout con 5 agentes por área

$ARGUMENTS
