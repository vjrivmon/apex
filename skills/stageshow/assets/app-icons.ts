// Marcas geométricas de sustitución.
// El fichero upstream `assets/app-icons.ts` incrusta PNG sacados de los
// bundles de las aplicaciones. NOTICE.md los deja fuera de la licencia MIT
// y esta copia de APEX no los redistribuye. Para un producto real, usa
// los iconos que ese producto permite.

const mark = (fill: string): string =>
  'data:image/svg+xml,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="${fill}"/></svg>`,
  )

export const mail = mark('#57534e')
export const calendar = mark('#78716c')
export const testFlight = mark('#a8a29e')
export const slack = mark('#44403c')
export const figma = mark('#292524')
export const notion = mark('#1c1917')
