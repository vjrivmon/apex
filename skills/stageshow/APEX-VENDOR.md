# Copia de Stageshow en APEX

Stageshow es una skill de Benji Taylor para stills de producto, animaciones,
bentos y demos con cursor. El proceso que APEX adopta es mirar, historia,
ejemplo, filmar y correcciones.

## Origen y licencia

- Repositorio: <https://github.com/benjitaylor/skills>
- Commit vendido: `802057409787133703c56001080169e347305572`
- Instalación upstream: `npx skills add benjitaylor/skills --skill stageshow`
- Licencia del código y de la documentación de la skill: MIT. Copyright (c)
  2026 Benji Taylor. El texto completo está en `LICENSE`.
- Aviso de terceros de upstream: `NOTICE.md`.

La licencia MIT permite copiar, modificar y redistribuir la skill si se
conserva el aviso de copyright. Esta copia lo conserva.

## Qué entra en esta copia

`SKILL.md`, `kit/`, `examples/`, `references/`, `scripts/`, `teaching/`,
`playground/`, `package.json` y `package-lock.json`. Las fotos de
`examples/wikipedia/` están dedicadas bajo CC0 1.0; autores y fuentes están
en `examples/wikipedia/PHOTOS.md`.

Los SVG de `kit/brands/` que sí se incluyen traen su propia licencia en el
mismo directorio: SVGL (MIT), payment-icons (Apache 2.0), Cryptocurrency
Icons (CC0 1.0) y Simple Icons (CC0 1.0). Esas licencias no transfieren las
marcas. El uso de cada marca sigue las condiciones de su titular.

## Qué se dejó fuera

| Fichero upstream | Motivo |
|---|---|
| `assets/app-icons.ts` (PNG embebidos) | `NOTICE.md` dice que son ilustraciones sacadas de los bundles de las apps y que no cubre la licencia MIT. Aquí hay un sustituto geométrico, obra de esta copia, con los mismos nombres de export para que los ejemplos sigan compilando. |
| `kit/brands/linear.svg`, `linear-dark.svg` | Marca oficial de Linear, sujeta a sus condiciones de marca. |
| `kit/brands/amex.svg`, `amex-tile.svg` | Marca oficial de American Express. |
| `kit/brands/usdc.svg` | Marca oficial de Circle (USDC). |

Esas claves se quitaron de `kit/brands/index.ts`. En `examples/kit-extras` el
tercer `BrandMark` usa `github` (SVGL, MIT) en lugar de `linear`.

## Cambios de APEX sobre el texto upstream

- Sección «Uso en APEX» al inicio de `SKILL.md`, y triggers en español en
  el frontmatter.
- Notas de la copia en `references/brands.md` y `kit/brands/SOURCES.md`.
- Este fichero.

El workflow en inglés de `SKILL.md` (look, story, example, film, corrections)
sigue siendo el de upstream.
