# APEX — Diseña Sistemas Multi-Agente, Inteligentemente

> Sistema de skills para Claude Code que guía el ciclo completo de desarrollo de
> software: desde la idea hasta el mantenimiento. Con persistencia de contexto
> entre sesiones, tutor socrático, y 14 fases de desarrollo con gate 10.5 de seguridad.

## Uso en Codex

APEX también tiene una skill de entrada para Codex que reutiliza el router,
las fases y las skills de este repositorio. Con el entorno `.venv` de APEX
ya instalado, ejecuta desde la raíz del repositorio:

```bash
mkdir -p ~/.agents/skills
ln -s "$PWD/skills/apex" ~/.agents/skills/apex
codex mcp add apex --env APEX_AUTO_LAUNCH_HUB=0 -- "$PWD/.venv/bin/python3" "$PWD/mcp/apex_server.py"
```

Si el enlace `~/.agents/skills/apex` ya existe, comprueba su destino antes de
repetir la instalación. Reinicia Codex después de registrar el MCP y usa
`$apex` seguido de tu petición (o selecciona la skill APEX). Es el equivalente
del comando `/apex` de Claude Code; escribir `/apex` como texto también está
contemplado por la descripción de la skill, pero no registra un slash command
nativo. Ver [skills de Codex](https://learn.chatgpt.com/docs/build-skills).

El servidor debe heredar el directorio del proyecto abierto: no configures su
`cwd` al repositorio APEX, porque la BD se selecciona por directorio de trabajo.
`APEX_AUTO_LAUNCH_HUB=0` evita arrancar el Hub y abrir el navegador al conectar
Codex. Sin esa variable se conserva el comportamiento anterior de Claude Code.

Los hooks y agentes instalados en `~/.claude/` no se cargan en Codex. La skill
adapta las llamadas de herramientas, registra el progreso explícitamente y
mantiene los gates del MCP; no instala los hooks de Claude ni sus temporizadores.

## Uso en OpenCode

OpenCode descubre la skill APEX enlazada en `~/.agents/skills/apex`. Registra
el servidor MCP globalmente y deja que herede el directorio del proyecto activo:
si `apex` o el comando global ya existen, comprueba su destino antes de
repetir la instalación.

```bash
cd ~/RoadToDevOps/apex
opencode mcp add apex --global --env APEX_AUTO_LAUNCH_HUB=0 -- \
  "$PWD/.venv/bin/python3" "$PWD/mcp/apex_server.py"
mkdir -p ~/.config/opencode/commands
ln -s "$PWD/.opencode/commands/apex.md" \
  ~/.config/opencode/commands/apex.md
opencode mcp list
```

El comando nativo `/apex` usa la skill compartida y las herramientas MCP bajo
`tools.apex`. No configures `cwd` para el servidor: APEX selecciona
`.apex/context.db` a partir del workspace actual. La variable evita que el MCP
arranque APEX Hub automáticamente. Comprueba el nombre devuelto por
`apex_get_context` antes de escribir; los hooks de Claude Code no se ejecutan en
OpenCode. El contexto y la búsqueda de la base se consultan mediante las
herramientas APEX; no se expone SQL arbitrario.

## El Problema

**Claude Code pierde el hilo cuando un proyecto ya está en marcha.** Las
herramientas existentes (MVP-Mode, scaffolders) funcionan para el inicio (idea →
código), pero después del scaffolding inicial, te quedas sin guía. Las fases
intermedias de desarrollo son un punto ciego.

## La Solución

APEX **no es una app web**. Es un sistema de **skills, commands y una BD SQLite
contextual** que vive dentro de Claude Code. Cada proyecto tiene un
`.apex/context.db` que persiste entre sesiones para que Claude Code siempre
sepa:

- En qué fase está el proyecto
- Qué decisiones se tomaron y por qué
- Qué errores se cometieron (y no repetirlos)
- Cuál es el siguiente paso lógico
- Qué componentes están implementados, testeados o verificados

## Características

| Característica             | Descripción                                                                    |
| -------------------------- | ------------------------------------------------------------------------------ |
| **Tutor Socrático**        | Cuestiona tus ideas antes de diseñar. Filtra las débiles, fortalece las buenas |
| **14 Fases Guiadas + Gate 10.5** | Desde el socrático hasta el mantenimiento. Gate AgentArmor bloquea deploy. |
| **Context DB**             | SQLite con temporal facts, progressive disclosure, FTS5, y error memory        |
| **Temporal Facts**         | Las decisiones tienen `valid_from`/`invalid_from` (patrón Graphiti)            |
| **Progressive Disclosure** | 3 niveles de contexto: compact (~200tk), timeline (~800tk), full (~2000tk)     |
| **Error Memory**           | Bidireccional (Claude + usuario), con detección de recurrencia                 |
| **LLM-Wiki**               | Knowledge base por proyecto (patrón Karpathy) con Markdown interconectado      |
| **FlowGuardian**           | Vigila que se siguen las fases. Bloquea si la anterior no está completa        |
| **SolutionTypeAdvisor**    | Propone CLI/bot/MCP/app según el problema — no todo es dashboard               |
| **IterationGuide**         | Guía para fases 12-14 donde MVP-Mode fallaba                                   |

## Las 14 Fases + Gate 10.5

```
 0. Socrático      → Cuestiona, filtra, refina la idea
 1. Tipo solución  → CLI/bot/MCP/app/agente según el problema
 2. Diseño         → C4, wireframes (Pencil MCP), user maps
 3. SPEC           → Por fases con checkpoints
 4. Edge cases     → ANTES del código, siempre
 5. Scaffold       → Estructura + config + .apex/context.db
 6. Core           → Domain, ports, agentes
 7. Infraestructura→ BD, LLM, scraping, adaptadores
 8. Integración    → Conectar todo, Streamlit para validar
 9. Testing        → Unit + integration + E2E
10. Seguridad      → OWASP, auth, headers, audit
11. Deploy         → Docker, Tailscale, systemd
────────────────── MVP-Mode paraba aquí ──────────────────
12. Iteración      → Features, bugs, mejoras CON CONTEXTO
13. Escalado       → Performance, caching, monitoring
14. Mantenimiento  → Migraciones, backups, actualizaciones
```

## Arquitectura

```
~/RoadToDevOps/apex/           ← Repositorio APEX
├── lib/
│   ├── context_db.py          ← BD SQLite contextual (temporal facts, FTS5)
│   ├── project_root.py        ← Resolución de la raíz del proyecto (una sola)
│   ├── advisor.py             ← Advisor: revisar y proponer (no escribe código)
│   ├── curator.py             ← Curador local opt-in (APEX_CURATOR_MODEL)
│   ├── vfs.py                 ← VirtualFS cross-project read-only
│   └── wiki_scaffold.py       ← Generador de knowledge base (patrón Karpathy)
├── mcp/
│   ├── apex_server.py         ← Servidor MCP (las tools)
│   └── handlers/              ← Un handler por tool
├── commands/
│   ├── apex.md                ← Comando /apex para Claude Code
│   └── phases/                ← Las 15 fases + el gate 10.5
├── skills/
│   ├── socratic/SKILL.md      ← Tutor socrático (3-5 rondas)
│   ├── architect/SKILL.md     ← SolutionTypeAdvisor
│   ├── flow-guardian/SKILL.md ← Vigilante de fases
│   └── iterate/SKILL.md       ← Guía para fases 12-14
├── templates/                 ← Lo que se scaffoldea a cada proyecto
│   ├── devops/                ← Hook de gitleaks, CI
│   ├── commands/              ← Slash commands de APEX
│   └── apex-security/         ← Capas AgentArmor
├── tests/                     ← La suite completa
├── backend/                   ← Legacy declarado, sin usar (ver AGENTS.md)
└── .apex/                     ← El contexto del propio proyecto APEX
```

`frontend/` ya no existe: el único frontend de APEX es `apex-hub`, en
`~/RoadToDevOps/apex-hub/`. `backend/` sigue en el árbol por inercia
histórica desde el Sprint 7 y no se carga en el flujo actual.

### Por proyecto (generado por /apex)

```
mi-proyecto/
├── .apex/
│   ├── context.db             ← Estado, decisiones, errores, componentes
│   └── wiki/                  ← Knowledge base del proyecto
│       ├── SCHEMA.md          ← Convenciones y taxonomía
│       ├── index.md           ← Catálogo de contenido
│       ├── log.md             ← Registro cronológico
│       ├── entities/          ← Productos, servicios, componentes
│       ├── concepts/          ← Ideas, patrones, principios
│       ├── comparisons/       ← Análisis comparativos
│       ├── queries/           ← Preguntas frecuentes compiladas
│       └── raw/               ← Fuentes inmutables
```

## Context DB — Progressive Disclosure

```python
db = ApexContextDB("proyecto/.apex/context.db")

# Compact (~200 tokens) — para agentes rápidos
await db.get_context("compact")
# → Fase actual + meta + próximos pasos

# Timeline (~800 tokens) — para decisiones
await db.get_context("timeline")
# → + decisiones vigentes + errores recurrentes + componentes

# Full (~2000 tokens) — para contexto completo
await db.get_context("full")
# → + wiki index + sesiones recientes + decisiones invalidadas
```

## Temporal Facts

Las decisiones no se borran — se invalidan:

```python
d1 = await db.add_decision("stack", "Node.js", "Rápido de prototipar")
d2 = await db.add_decision("stack", "Python + FastAPI", "Mejor para ML")
await db.invalidate_decision(d1, "Python tiene mejor ecosistema de agentes")
# d1 pasa al historial, d2 es la decisión vigente
```

## Error Memory

Errores bidireccionales con detección de recurrencia:

```python
await db.add_error("claude", "Frontend antes de backend", "Backend-first siempre")
await db.add_error("claude", "Frontend antes de backend", "Backend-first SIEMPRE")
# recurrence_count = 2, se prioriza en el contexto
```

## Instalación

```bash
git clone https://github.com/vjrivmon/apex.git ~/RoadToDevOps/apex
cd ~/RoadToDevOps/apex
python3 -m venv .venv
.venv/bin/pip install aiosqlite
```

## Uso

Desde cualquier proyecto con Claude Code:

```
/apex  → Detecta si es proyecto nuevo o existente y guía al usuario
```

## Tests

```bash
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -v
# 28 passed in 0.14s
```

## Inspiraciones

| Fuente                                                                                 | Lo que aporta                                       |
| -------------------------------------------------------------------------------------- | --------------------------------------------------- |
| [Karpathy LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | Knowledge base en Markdown con wikilinks            |
| [OpenClaw Dreaming](https://github.com/openclaw/openclaw)                              | Promoción de señales cortas a memoria permanente    |
| [Graphiti/Zep](https://github.com/getzep/graphiti)                                     | Temporal facts con `valid_at`/`invalid_at`          |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent)                           | Memory manager + context compression                |
| [gstack](https://github.com/garrytan/gstack)                                           | Sprint lifecycle: Think→Plan→Build→Review→Test→Ship |
| [claude-mem](https://github.com/thedotmack/claude-mem)                                 | Progressive disclosure (3 capas de búsqueda)        |

## Roadmap

- [ ] MCP server para acceder a context.db desde Claude Code
- [ ] Integración con Pencil MCP para diseños automáticos
- [ ] Dreaming: promoción automática de señales a memoria permanente
- [ ] Skill de security audit (inspirado en gstack `/cso`)
- [ ] Skill de code review (agente verificador)
- [ ] Embeddings locales (nomic-embed-text) para búsqueda semántica en wiki

## Autor

**Vicente Rivas Monferrer** — Desarrollador Full Stack | IA/ML | UPV

- Primer puesto nacional Líderes Digitales Universitarios 2025 (Telefónica)
- Cátedra ENIA-UPV

## Licencia

MIT
