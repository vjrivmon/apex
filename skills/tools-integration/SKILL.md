# Integración de Herramientas Externas

## Herramientas disponibles para APEX

### Diseño

| Herramienta       | Tipo               | Uso                                   | Activación                                                         |
| ----------------- | ------------------ | ------------------------------------- | ------------------------------------------------------------------ |
| **Pencil MCP**    | MCP (ya instalado) | Canvas de diseño, wireframes, mockups | `mcp__pencil__batch_design`                                        |
| **Paper.design**  | MCP (desktop)      | Diseño → JSX/Tailwind directo         | `claude mcp add paper --transport http http://127.0.0.1:29979/mcp` |
| **Google Stitch** | Skills + MCP       | Diseño completo → React pipeline      | Skills: stitch-design, stitch-loop, design-md                      |
| **AI Designer**   | MCP (cloud)        | HTML rápido desde texto               | Solo si Pencil/Paper no disponibles                                |

**Flujo de diseño recomendado:**

1. Pencil MCP para wireframes y mockups (fase 2)
2. Stitch para generar diseño completo desde prompt (fase 2)
3. Paper.design para exportar a JSX/Tailwind (fase 6-8)

### Browser y Testing

| Herramienta        | Tipo               | Uso                                    | Activación                                 |
| ------------------ | ------------------ | -------------------------------------- | ------------------------------------------ |
| **dev-browser**    | CLI (instalado)    | Scraping, testing, QA con browser real | `Bash(dev-browser --headless ...)`         |
| **Playwright MCP** | MCP (ya instalado) | Screenshots, verificación visual       | `mcp__puppeteer__*` o `mcp__playwright__*` |

**Flujo de testing recomendado:**

1. dev-browser para tests de scraping y flujos de usuario (más rápido)
2. Playwright MCP para screenshots de verificación visual
3. Combinar ambos en fase 9 (testing)

### Skills

| Herramienta   | Tipo | Uso                                      | Activación                  |
| ------------- | ---- | ---------------------------------------- | --------------------------- |
| **skills.sh** | CLI  | Buscar e instalar skills de la comunidad | `npx skills find <keyword>` |

**Cuándo buscar skills externos:**

- Antes de implementar algo que parece genérico (auth, billing, testing
  framework)
- Cuando un agente no tiene conocimiento de un dominio específico
- `npx skills find <keyword>` → evaluar → `npx skills add <repo> --global`

### Memoria

| Herramienta    | Tipo           | Uso                              | Activación                |
| -------------- | -------------- | -------------------------------- | ------------------------- |
| **context.db** | SQLite local   | Memoria por proyecto (APEX core) | Herramientas MCP apex\_\* |
| **OpenMemory** | Self-hosted    | Memoria cross-proyecto con graph | `docker compose up` + MCP |
| **LLM-Wiki**   | Markdown local | Knowledge base por proyecto      | `.apex/wiki/`             |

**Flujo de memoria:**

1. context.db para todo lo del proyecto actual (decisiones, errores, fases)
2. LLM-Wiki para conocimiento compilado (entidades, conceptos)
3. OpenMemory (futuro) para memoria cross-proyecto y perfil de usuario

## Reglas

1. **Diseño visual → SIEMPRE Pencil MCP primero**. Paper/Stitch como
   complemento.
2. **Browser testing → dev-browser para flujos, Playwright para screenshots**.
3. **Skills faltantes → buscar en skills.sh ANTES de implementar desde cero**.
4. **NUNCA usar emojis como iconos**. Usar Lucide/Phosphor/Heroicons.
5. **NUNCA describir diseños por texto**. Usar Pencil/Paper/Stitch para mockups.
