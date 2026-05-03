# Formato de ADR

Los ADRs viven en `docs/adr/` (convención Matt Pocock) o en `wiki/decisions/` (convención APEX). Si el proyecto tiene `wiki/decisions/`, prefiérelo.

- `docs/adr/`: numeración secuencial `0001-slug.md`, `0002-slug.md`...
- `wiki/decisions/`: timestamped `YYYY-MM-DD-slug.md`

Crea el directorio perezosamente — sólo cuando haga falta el primer ADR.

## Plantilla

```md
# {Título corto de la decisión}

{1-3 frases: cuál es el contexto, qué decidimos y por qué.}
```

Eso es todo. Un ADR puede ser un solo párrafo. El valor está en registrar *que* se tomó una decisión y *por qué* — no en rellenar secciones.

## Secciones opcionales

Inclúyelas sólo cuando aporten valor genuino. La mayoría de ADRs no las necesitan.

- **Status** en el frontmatter (`proposed | accepted | deprecated | superseded by ADR-NNNN`) — útil cuando las decisiones se revisitan
- **Considered Options** — sólo cuando las alternativas rechazadas merecen recordarse
- **Consequences** — sólo cuando hay efectos no obvios aguas abajo que conviene señalar

## Numeración (sólo `docs/adr/`)

Escanea `docs/adr/` para el número más alto e incrementa en uno. En `wiki/decisions/` usa fecha del día (`date -I`) + slug kebab-case.

## Cuándo ofrecer un ADR

Los tres deben ser ciertos:

1. **Difícil de revertir** — el coste de cambiar de opinión más tarde es significativo
2. **Sorprendente sin contexto** — un futuro lector mirará el código y se preguntará "¿por qué demonios lo hicieron así?"
3. **Resultado de un trade-off real** — había alternativas genuinas y se eligió una por motivos específicos

Si una decisión es fácil de revertir, salta — la revertirás. Si no es sorprendente, nadie se preguntará por qué. Si no había alternativa real, no hay nada que registrar más allá de "hicimos lo obvio".

### Qué califica

- **Forma arquitectónica.** "Usamos monorepo." "El write model es event-sourced; el read model se proyecta a Postgres."
- **Patrones de integración entre contextos.** "Ordering y Billing se comunican por eventos de dominio, no HTTP síncrono."
- **Elecciones tecnológicas con lock-in.** Base de datos, message bus, proveedor de auth, target de despliegue. No cualquier librería — sólo las que costarían un trimestre cambiar.
- **Decisiones de límite y alcance.** "Los datos del Customer los posee el contexto Customer; otros contextos referencian sólo por ID." Los "no" explícitos son tan valiosos como los "sí".
- **Desviaciones deliberadas del camino obvio.** "Usamos SQL manual en vez de ORM porque X." Cualquier cosa donde un lector razonable asumiría lo contrario. Esto evita que el siguiente ingeniero "arregle" algo que era deliberado.
- **Restricciones no visibles en el código.** "No podemos usar AWS por requisitos de cumplimiento." "Los tiempos de respuesta deben estar bajo 200ms por contrato con un partner."
- **Alternativas rechazadas cuando el rechazo no es obvio.** Si consideraste GraphQL y elegiste REST por razones sutiles, regístralo — si no, alguien sugerirá GraphQL otra vez en seis meses.
