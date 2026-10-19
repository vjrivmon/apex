---
name: brand-identity
description: Construye el manual de identidad profundo (logo escalable, favicon, app icon, variantes) en fase 2b de /apex, tras el moodboard y antes de tokens. Triggers ES/EN — identidad de marca, brand identity, logo, brand book, manual de marca, favicon, app icon.
---

# BrandIdentity — Manual de identidad profundo y logo escalable

## Cuándo activar

- **Fase 2b (Identidad visual)** — tras moodboard, antes de tokens.
- Cuando el usuario dice "logo", "manual de identidad", "sistema de marca",
  "brand book", "favicon", "app icon".
- Cuando el proyecto entra en fase de producción (Fase 11) sin logo
  escalable — bloquear el deploy hasta resolverlo.

## North star

Este skill no existe para "generar un logo decente". Existe para producir
**identidades del nivel de**:

- **drapz.design** — referencia de manual de identidad profesional
  (estudiar antes de arrancar)
- **Solaris** (Buffet Designs + Bitmap Studio) — logo system completo +
  GIF de movimiento + app icon + browser tab + en device
- **Talo** — logo minimalista con animales, brand shapes, mockup device
- **Delegento** — 4 variantes completas (yellow/coral/orange/blue) con
  primary logo, reversed logo, button states, paleta, typography,
  brand shapes, brand in use, brand voice
- **Bloom** — gradientes soft + app icon + landing + browser tab
- **Havernex** — neón + gamma blue + brand shapes en grid + posters

Si lo que vas a entregar no está al nivel de estos ejemplos, no es un
manual de identidad — es un logo decorativo.

## Fundamento: backend-first, frontend con igual o más tiempo

Vicente trabaja backend primero (arquitectura sólida, datos reales,
tests). Cuando llega esta skill, el backend **debe estar funcionando**.
A partir de aquí se dedica **al menos el mismo tiempo** que al backend
al sistema de marca y al frontend. No es "la parte bonita al final" —
es la fase que convierte un producto funcional en una marca vendible.

## Multi-tool obligatorio (no cerrarse a una sola)

Usar en paralelo **al menos dos** de:

| Tool | Uso principal | Cuándo brillaaa |
|------|--------------|----------------|
| **Pencil MCP** | Wireframes, layouts rápidos | Exploración inicial, sketches |
| **Google Stitch** | Componentes y estilo completo | Páginas/flows con estética definida |
| **Figma MCP** | Manual de identidad, tokens, mockups finos | Output final editable |
| **Excalidraw MCP** | Diagramas, navegación, flujos | Explicar arquitectura visual |
| **Imagen/DALL·E/SDXL** | Backgrounds, patrones, mockups en contexto | Escenas realistas (device mockups) |

**Regla**: nunca decidir identidad con una sola herramienta. Generar la
misma propuesta en ≥2 tools distintas y comparar lado a lado antes de
elegir. La disciplina aquí evita el sesgo estilístico de cada tool.

## Logo system — entregables obligatorios

Un logo no es "un SVG". Es un **sistema** que escala de 16px a billboard.
Entregables mínimos:

### Variantes

- **Primary** — uso por defecto, fondo claro.
- **Reversed** — fondo oscuro (NO es solo "invertir color": re-balancear).
- **Monochrome** — 1 tinta, para impresiones B/N o embossed.
- **Icon only** — la marca sin el wordmark (cuando no hay espacio).
- **Wordmark only** — sólo la tipografía (en cabeceras largas).
- **Horizontal** vs **stacked/vertical** — según contexto.

### Escalas obligatorias

El logo debe verse nítido y legible en todos estos tamaños:

| Uso | Tamaño |
|-----|--------|
| Favicon | 16×16, 32×32 |
| App icon (iOS/Android) | 192×192, 512×512, 1024×1024 |
| Browser tab | 32×32 |
| Navbar web | 24-32 px de alto |
| Business card | 32 mm × 12 mm |
| Presentación | 240 px de alto |
| Billboard / hero | vector, sin límite |

Para cada escala, **verificar con screenshot** que:
1. Se lee el wordmark sin forzar la vista.
2. El icon conserva la forma distintiva (no se pierde detalle).
3. Contraste cumple WCAG AA con el fondo objetivo.

### Área de respeto y grid

- Definir **clear space** (área mínima alrededor del logo sin otros
  elementos). Típicamente la altura de la "x-height" del wordmark.
- Construcción en **grid geométrico** — publicar el grid como parte del
  manual (como Havernex publica sus ejes).

## Sistema de marca (más allá del logo)

### Paleta

- **Primary accent** (1 color que define la marca).
- **Secondary accent** (1-2 soporte).
- **Neutrales**: 5-7 tonos bg/surface/text/border.
- **Status**: success, warning, error, info.
- **Dark mode counterpart** si la marca lo soporta.

Cada color documentado con **hex + rol + ejemplo de uso**. Contraste
WCAG AA ≥ 4.5:1 para texto normal, 3:1 para texto grande.

### Tipografía

- **Serif** (opcional, para titulares emocionales).
- **Sans display** (hero, CTAs).
- **Sans body** (párrafos).
- **Mono** (código, labels de sistema).

Documentar **escala tipográfica completa** (xs..5xl con line-height y
letter-spacing). Preferir fuentes open-source (Google Fonts, Fontshare)
por licencia y rendimiento.

### Brand shapes / motivos

Como en Delegento (arrows, cuadrados, estrellas) o Havernex (grids de
gradiente), un **motivo visual secundario** además del logo. Esto
multiplica las aplicaciones de marca (posters, social, mockups).

### Brand voice

Documentar **3 adjetivos** que rigen el tono (ej. "modern · trustworthy ·
professional" en Delegento; "minimal · editorial · premium" en vr-web).

## Mockups obligatorios para presentar al usuario

Antes de aprobar la identidad, generar capturas realistas en:

1. **Mobile** — pantalla de inicio con app icon, navbar del producto.
2. **Tablet** — vista landing en iPad/Surface.
3. **Desktop** — hero + sección secundaria.
4. **Browser tab** — favicon + título (como en Bloom, Solaris).
5. **Business card** — presentación física.
6. **Social share image** (1200×630) con logo + tagline.
7. **App icon en grilla iOS/Android** con otras apps reales alrededor
   (test de contraste y memorabilidad).

Todas estas se pueden generar con Stitch/Figma MCP/mockup tools. No
aceptar presentaciones con solo "el SVG solo sobre fondo blanco".

## Regla cross-project (OBLIGATORIA)

Antes de proponer cualquier dirección de marca:

```
apex_search_cross_project(query="identidad <dominio del proyecto>")
apex_search_cross_project(query="paleta logo mockup")
```

Consultar también `~/.apex/wiki/brand/design-inspiration-*.md` — las
notas semanales del skill `design-research` tienen las últimas
referencias estudiadas.

## Protocolo de verificación antes de declarar la fase 2b completa

- [ ] `apex_search_cross_project` ejecutado sobre identidad y patrones.
- [ ] Biblioteca `design-research` consultada (≥2 referencias citadas).
- [ ] Moodboard con ≥3 direcciones aprobado por el usuario.
- [ ] Identidad construida en ≥2 herramientas de diseño (ej. Pencil +
      Stitch, o Figma + Stitch).
- [ ] Logo system con ≥4 variantes (primary, reversed, monochrome, icon).
- [ ] Logo verificado en ≥5 tamaños (favicon, app icon, navbar, card,
      hero) con screenshot de cada uno.
- [ ] Paleta completa con roles semánticos + contraste WCAG AA
      calculado.
- [ ] Tipografía con escala completa y line-heights.
- [ ] Brand shape/motivo definido y aplicado a ≥3 assets.
- [ ] Mockups generados para ≥5 superficies (mobile, tablet, desktop,
      browser tab, app icon grid).
- [ ] Brand voice con ≥3 adjetivos rectores.
- [ ] `apex_add_decision` categoría `design` por cada bloque (logo,
      paleta, tipografía, motion, voice).
- [ ] Usuario aprobó explícitamente antes de avanzar a fase 3.

## Output físico en `.apex/brand/`

```
.apex/brand/
├── identity/
│   ├── logo/
│   │   ├── primary.svg
│   │   ├── reversed.svg
│   │   ├── monochrome.svg
│   │   ├── icon.svg
│   │   ├── favicon-16.png, favicon-32.png
│   │   ├── app-icon-192.png, 512.png, 1024.png
│   │   └── grid.svg (construcción geométrica)
│   ├── palette.md (+ preview PNG)
│   ├── typography.md
│   ├── shapes.svg (motivos secundarios)
│   └── voice.md (3 adjetivos + ejemplos de copy)
├── design-system/
│   ├── tokens.css (variables semánticas)
│   └── tokens.json (equivalente para tooling)
├── mockups/
│   ├── mobile.png
│   ├── tablet.png
│   ├── desktop.png
│   ├── browser-tab.png
│   ├── business-card.png
│   ├── social-share.png
│   └── app-icon-grid.png
└── manual.md (resumen con links a todo lo anterior)
```
