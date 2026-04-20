# DesignResearch — Biblioteca rotativa de inspiración visual

## Cuándo activar

- **Fase 2a (Moodboard)**: antes de proponer dirección visual al usuario.
- **Semanalmente (automático)**: el hook `weekly-design-lint.py` ejecuta
  cada 7 días y resume novedades en `.apex/wiki/brand/`.
- **On-demand**: cuando el usuario pide "inspiración", "referencias",
  "qué patrones de X están en tendencia", "cómo se diseña Y ahora mismo".

## Objetivo

Mantener la identidad visual de APEX (y cada proyecto) calibrada con lo
mejor del estado del arte. Evitar la estética "AI default" consultando
periódicamente bibliotecas curadas, no la primera idea que salga.

## Biblioteca (50+ referencias clasificadas)

### Sistemas de diseño y principios

- <https://github.com/rohitg00/awesome-claude-design> — recopilación
  oficial de Claude Design (north star cuando se diseña con Claude)
- <https://github.com/VoltAgent/awesome-claude-design> — fork/relacionado,
  incluir principios y comparar
- <https://drapz.design> — referencia de manual de identidad profesional
- <https://lawsofux.com> — Leyes de UX aplicables en fase 2
- <https://component.gallery> — Sistemas de diseño reales

### Curadurías generales

- <https://curations.supply> — Design Library curada
- <https://curated.design> — Diseño web curado
- <https://godly.website> — Inspiración general
- <https://minimal.gallery> — Páginas minimalistas

### Landing pages y SaaS

- <https://landing.love>
- <https://lapa.ninja>
- <https://landingfolio.com>
- <https://saaspo.com>
- <https://saasframe.io>

### Componentes específicos

- <https://navbar.gallery>
- <https://cta.gallery>
- <https://pageflows.com>

### Mobile

- <https://mobbin.com>
- <https://sleek.design>

### Brand, tipografía, iconos

- <https://rebrand.gallery> — Rediseños
- <https://uncut.wtf> — Fuentes
- <https://hugeicons.com> — Iconografía

### Animación y motion

- <https://60fps.design>
- <https://appmotion.design>

### Identidad visual (casos referencia)

Referencias concretas estudiadas por el usuario — cuando se diseñe un
sistema de marca completo, apuntar a este nivel:

- **Solaris** (Buffet Designs + Bitmap Studio) — logo system + GIF de
  movimiento + app icon + browser tab en un solo deck
- **Talo** — logo minimalista + brand shapes + mockup en device
- **Delegento** — 4 variantes completas (yellow/coral/orange/blue) con
  logo system, button states, paleta, typography, brand shapes, brand
  in use, brand voice
- **Bloom** — identidad soft/pink con gradientes + app icon + landing
- **Havernex** — neon yellow + gamma blue + brand shapes en grid

## Tool de consulta

Antes de decidir, usar:

```
apex_search_cross_project(query="<tópico visual>")
```

Y complementar con `WebFetch` a 2-3 URLs de la biblioteca relevantes al
caso. Nunca decidir con una sola referencia.

## Rutina semanal (hook WeeklyLint)

El hook `.claude/hooks/weekly-design-lint.py` ejecuta:

1. Escoge 3 URLs de la biblioteca rotando por categoría.
2. Hace `WebFetch` a cada una.
3. Resume top 3 patrones emergentes en
   `.apex/wiki/brand/design-inspiration-YYYY-WW.md` (ISO week).
4. Llama `apex_wiki_add` con el resumen etiquetado `design-inspiration`.

Esto mantiene el "radar" visual activo sin requerir atención manual —
cuando toque la fase 2 de un proyecto nuevo, ya hay 4-6 semanas de
referencias recientes esperando.

## Output esperado al activar on-demand

1. Consulta cross-project relevante ejecutada.
2. 3-5 referencias concretas con URL + por qué aplican.
3. Mínimo 2 herramientas de diseño usadas para generar mockups
   (Pencil + Stitch, o Figma + Stitch, etc.) — ver `design-system/SKILL.md`
   y `brand-identity/SKILL.md`.
4. Decisión registrada con `apex_add_decision` categoría `design`.
