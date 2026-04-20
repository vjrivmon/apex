# Fase 2 — Diseno

REGLA: NUNCA describas un diseno por texto. Usa las herramientas de diseno
para crear mockups visuales. Si la decision afecta al aspecto visual, DEBE
acompanarse de un artefacto visual.

Esta fase tiene 3 bloques: Arquitectura, Identidad Visual, y UX. Se ejecutan EN
ORDEN. No saltar a wireframes sin tener la paleta definida.

## Herramientas de diseno y su mejor uso

| Herramienta   | Mejor para                                       | MCP tool prefix / skill              |
| ------------- | ------------------------------------------------ | ------------------------------------ |
| Pencil MCP    | Wireframes, layouts, mockups detallados          | `mcp__pencil__*`                     |
| Paper.design  | Exportar a JSX/Tailwind, iteracion rapida        | `mcp__paper__*` (si disponible)      |
| Google Stitch | Generacion completa de pantallas, design systems | skill: stitch-design, stitch-loop    |
| AI Designer   | Prototipado HTML rapido                          | `mcp__aidesigner__*` (si disponible) |
| Excalidraw    | Diagramas, flujos, mapas de navegacion           | `mcp__claude_ai_Excalidraw__*`       |
| Figma MCP     | Manual de identidad, design tokens, mockups finos| `mcp__figma__*` (si disponible)      |

El agente debe decidir cual usar para cada tarea. **Obligatorio usar al menos
2 herramientas distintas** en identidad visual (Bloque B). Si hay duda,
PREGUNTAR al usuario.

## Bloque A: Arquitectura

- **[2a]** Diagrama C4 (context + container) con Mermaid. Validar que la
  arquitectura tiene sentido antes de continuar. Registrar con
  `apex_add_decision(category="architecture")`.
- **[2b]** Diagrama C4 componentes (si es complejo). Descomponer cada container
  en sus componentes internos.

## Bloque B: Identidad Visual (Design System)

OBLIGATORIO si el proyecto tiene UI. Usar MULTIPLES herramientas de diseno +
awesome-design-md + skill `brand-identity` + skill `design-research`.

- **[2c]** Preferencias del usuario: ANTES de crear nada, consultar context.db
  para historial de estilos preferidos del usuario (buscar decisions con
  category="design"). Si hay historial: "En proyectos anteriores elegiste estilo
  X con paleta Y. Quieres mantener esa linea o explorar algo nuevo?" Si no hay
  historial: preguntar con AskUserQuestion mostrando opciones visuales.
- **[2d]** Moodboard COMPARATIVO: Generar moodboards en MULTIPLES herramientas:
  - Pencil MCP: moodboard con layout de referencia
  - Stitch (skill stitch-design): diseno de referencia desde prompt
  - Consultar awesome-design-md para DESIGN.md de apps similares.
  - Consultar `design-research` skill para rotacion semanal de inspiracion.
  Presentar las 2-3 opciones al usuario para que elija.
- **[2e]** Paleta de colores COMPLETA:
  - Brand: primary, secondary
  - Surfaces: background, surface, elevated, overlay
  - Text: primary, secondary, tertiary, muted, inverse
  - Status: success, warning, error, info
  - Borders, shadows, dividers
  Generar swatches visuales con Pencil MCP. Registrar en context.db Y en wiki:
  `apex_wiki_add(slug="concepts/design-system")`.
- **[2f]** Tipografia:
  - Heading family + fallbacks (ej: Geist, Inter Variable)
  - Body family + fallbacks
  - Mono family + fallbacks (ej: Berkeley Mono, Geist Mono)
  - Escala: display (48-72px), h1-h4, body, small, caption, micro
  - Pesos por nivel: display=500-600, body=400, emphasis=500-600
  - Letter-spacing por tamano (negativo en display, normal en body)
  - Line-height por nivel. Registrar en wiki design-system.
- **[2g]** Espaciado, radios y elevation:
  - Base unit (4px u 8px)
  - Escala: 2xs(2), xs(4), sm(8), md(16), lg(24), xl(32), 2xl(48), 3xl(64)
  - Border radius: none(0), sm(4), md(8), lg(12), xl(16), full(9999)
  - Elevation: flat, subtle, standard, elevated, dialog (shadow values)
  - Breakpoints: sm(640), md(768), lg(1024), xl(1280)
- **[2h]** Iconografia: Elegir paquete (Lucide, Phosphor, Heroicons) y tamanos
  estandar. **NUNCA emojis**. Registrar decision.
- **[2i]** Accesibilidad visual:
  - Verificar contraste WCAG AA minimo (4.5:1 para texto, 3:1 para grandes)
  - Touch targets minimo 44x44px
  - Focus visible en todos los interactivos
  - Roles ARIA documentados para componentes custom
  - Plan de screen reader para flujos principales

## Bloque C: UX y Pantallas

- **[2j]** Wireframes en MULTIPLES herramientas:
  - Pencil MCP para wireframes low-fi de cada pantalla
  - Stitch para un high-fi de la pantalla principal
  Presentar opciones al usuario para decidir direccion.
- **[2k]** Mapa de navegacion con Excalidraw MCP: Todas las pantallas como
  nodos, flechas entre ellas indicando que boton/link lleva a donde. Exportar
  como imagen.
- **[2l]** User flows: Documentar minimo 3 flujos:
  - Flujo principal (happy path)
  - Flujo secundario (alternativa)
  - Flujo de error (que pasa cuando algo falla)
  Formato: Accion → Pantalla → Resultado → Siguiente accion.
- **[2m]** Registrar TODOS los componentes detectados con `apex_add_component`.
- **[2n]** Guardar design system completo en wiki + context.db:
  `apex_wiki_add(slug="concepts/design-system", content="paleta+typo+spacing")`.
- **[2o]** `apex_set_phase(phase_number=2, status="completed")`.

## North star visual (referencias)

Apuntar al nivel de calidad de: `drapz.design`, Buffet Designs (Solaris),
Bitmap Studio (Solaris visual identity), Talo, Delegento (4 variantes), Bloom,
Havernex. Consultar `skills/brand-identity/SKILL.md`.

## Criterio de salida

- Diagramas C4 (context, container, componentes) generados con Mermaid.
- Design system completo en wiki (`concepts/design-system`).
- Al menos 2 herramientas de diseno usadas en Bloque B.
- Mapa de navegacion Excalidraw exportado.
- 3 user flows documentados.
- Fase marcada como `completed` en context.db.
