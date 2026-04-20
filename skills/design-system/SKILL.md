# DesignSystem — Identidad visual profesional y consistente

## Cuándo activar

- Fase 2 (Identidad Visual) de cualquier proyecto con UI.
- Cuando el usuario pide "paleta", "tipografía", "tokens", "design system",
  "moodboard", "wireframes", "mejorar diseño", "refactor visual".
- Antes de crear el primer componente UI en las fases 6-8.
- Cuando un review detecta inconsistencias (anchos distintos, emojis, márgenes
  rotos).

## Objetivo

Generar y mantener una identidad visual **coherente, accesible y
premium-first**: tokens semánticos, tipografía, espaciado, iconografía, y
componentes base. Evitar la estética genérica de "IA default".

## Regla cross-project (OBLIGATORIA — bloquea avance)

Antes de proponer o aplicar **cualquier** decisión visual, ejecutar:

```
apex_search_cross_project(query="<término>")
```

Con términos relevantes al contexto: `"ancho layout margen"`, `"emoji icono"`,
`"paleta colores dark"`, `"tipografía serif"`, `"breakpoint mobile"`,
`"accesibilidad contraste"`, etc.

Si la tool devuelve errores previos → **NO los repitas**. Muéstraselos al
usuario antes de decidir. Si devuelve decisiones vigentes → considéralas como
default y desvíate solo con razón explícita.

Esta regla existe porque el MCP repitió un bug de márgenes en `vr-web/casos`
que ya se había corregido en `FeedbackIA`. El hub.db lo sabía, el MCP no
preguntaba.

## Tokens semánticos (principio VoltAgent)

Nunca hardcodear valores. Siempre tokens con rol:

```css
/* ❌ NO */
.btn { background: #FF6B35; color: #fff; padding: 12px 24px; }

/* ✓ SÍ */
.btn {
  background: var(--accent-primary);
  color: var(--on-accent);
  padding: var(--space-3) var(--space-6);
}
```

Taxonomía mínima:

- **Color**: `--bg-*`, `--surface-*`, `--text-*`, `--border-*`,
  `--accent-primary`, `--accent-secondary`, `--state-{success,warn,error,info}`
- **Espaciado**: `--space-{0..12}` (base 4px u 8px, escalado consistente)
- **Tipografía**: `--font-serif`, `--font-sans`, `--font-mono`,
  `--text-{xs..5xl}`, `--leading-{tight,snug,normal,relaxed}`
- **Radii**: `--radius-{none,sm,md,lg,xl,full}`
- **Elevation**: `--shadow-{sm,md,lg,xl}`
- **Breakpoints**: `--bp-{sm,md,lg,xl,2xl}` (siempre mobile-first)

## Reglas absolutas (violar = falla la fase)

1. **Cero emojis** como iconos. Lucide / Phosphor / Heroicons / SVG custom.
   Documentado como error crítico recurrente en `focusnow`, `test-apex`,
   `sma-supermercados`.
2. **Ancho coherente** por página. No mezclar `max-w-[680px]` (lectura) con
   `max-w-5xl` (grid) sin un sistema claro. Decidir por tipo de layout:
   - Narrativo largo: 640–720px (55-75ch)
   - Dashboard / grid: 1024–1280px
   - Hero / impact: edge-to-edge con `padding` responsive
3. **Accesibilidad WCAG AA no-negociable**:
   - Contraste texto: 4.5:1 normal, 3:1 grande
   - Touch target: 44×44 px mínimo
   - Focus ring visible en todo interactivo
   - ARIA roles correctos
4. **Diseñar mobile-first**. Si no cabe en 360px, se rediseña, no se encoge.
5. **Español con tildes y eñes**. Siempre.

## Biblioteca de inspiración (consultar en fase 2c Moodboard)

El skill debe recomendar al usuario referencias de esta biblioteca antes de
proponer paletas/layouts. Elegir 2–3 según el tipo de proyecto:

### General / curaduría

- <https://curations.supply> — Design Library
- <https://curated.design> — Diseño web curado
- <https://godly.website> — Inspiración general
- <https://minimal.gallery> — Páginas minimalistas

### Landing pages

- <https://landing.love>
- <https://lapa.ninja>
- <https://landingfolio.com>

### SaaS

- <https://saaspo.com>
- <https://saasframe.io> — Componentes SaaS

### Componentes específicos

- <https://component.gallery> — Sistemas de diseño
- <https://navbar.gallery> — Barras de navegación
- <https://cta.gallery> — Secciones CTA
- <https://pageflows.com> — User flows reales

### Mobile

- <https://mobbin.com> — Apps móviles
- <https://sleek.design> — App builder con IA

### Brand / tipografía / iconos

- <https://rebrand.gallery> — Rediseños de marcas
- <https://uncut.wtf> — Fuentes
- <https://hugeicons.com> — Iconografía

### Animación y motion

- <https://60fps.design>
- <https://appmotion.design>

### Principios y teoría

- <https://lawsofux.com> — Leyes de UX
- Anthropic Skill Building Guide (progressive disclosure)
- `awesome-claude-design` (GitHub: VoltAgent) — principios Claude UI

## Output esperado de la fase 2

Cuando se completa esta skill en fase 2, debe existir:

1. `.apex/brand/design-system/tokens.{css,json}` con la taxonomía semántica.
2. `.apex/brand/identity/palette.md` (con preview de color y razonamiento).
3. `.apex/brand/identity/typography.md` (familias, escalas, line-heights).
4. `.apex/brand/identity/moodboard.md` con 3+ referencias de la biblioteca y
   justificación de elección.
5. Decisiones registradas con `apex_add_decision` categoría `design` para cada
   token set (paleta, tipografía, espaciado).
6. Componente base mostrando todos los tokens aplicados (ej. Button, Card).

## Protocolo de verificación antes de declarar fase 2 completa

- [ ] `apex_search_cross_project("ancho layout margen")` ejecutado
- [ ] `apex_search_cross_project("emoji icono iconografía")` ejecutado
- [ ] `apex_search_cross_project("paleta contraste accesibilidad")` ejecutado
- [ ] Moodboard tiene mínimo 3 referencias citadas con URL
- [ ] Tokens generados cubren color + tipografía + espaciado + radii
- [ ] Accesibilidad: contraste calculado explícitamente para cada par
      (bg/text) usado, ninguno bajo 4.5:1
- [ ] Usuario aprobó explícitamente antes de avanzar a fase 3
