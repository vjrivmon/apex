# Formato de CONTEXT.md

## Estructura

```md
# {Nombre del Contexto}

{Una o dos frases describiendo qué es este contexto y por qué existe.}

## Lenguaje

**Order**:
{Una descripción concisa del término}
_Evitar_: Purchase, transaction

**Invoice**:
Una solicitud de pago enviada a un Customer tras la entrega.
_Evitar_: Bill, payment request

**Customer**:
Una persona u organización que coloca Orders.
_Evitar_: Client, buyer, account

## Relaciones

- Una **Order** produce una o más **Invoices**
- Una **Invoice** pertenece a exactamente un **Customer**

## Diálogo de ejemplo

> **Dev:** "Cuando un **Customer** coloca una **Order**, ¿creamos la **Invoice** inmediatamente?"
> **Experto de dominio:** "No — una **Invoice** sólo se genera cuando se confirma un **Fulfillment**."

## Ambigüedades marcadas

- "account" se usaba para referirse tanto a **Customer** como a **User** — resuelto: son conceptos distintos.
```

## Reglas

- **Sé opinionado.** Cuando existan varias palabras para el mismo concepto, elige la mejor y lista las demás como aliases a evitar.
- **Marca conflictos explícitamente.** Si un término se usa de forma ambigua, sácalo a "Ambigüedades marcadas" con resolución clara.
- **Mantén las definiciones tensas.** Una frase máximo. Define qué ES, no qué hace.
- **Muestra relaciones.** Usa nombres en negrita y expresa cardinalidad cuando sea obvia.
- **Sólo incluye términos específicos del contexto del proyecto.** Conceptos generales de programación (timeouts, tipos de error, patrones de utilidad) no pertenecen aquí aunque el proyecto los use mucho. Antes de añadir un término, pregunta: ¿es un concepto único de este contexto, o es general? Sólo el primero pertenece.
- **Agrupa términos bajo subcabeceras** cuando emerjan clusters naturales. Si todos pertenecen a un único área cohesiva, una lista plana basta.
- **Escribe un diálogo de ejemplo.** Una conversación entre un dev y un experto de dominio que demuestre cómo los términos interactúan naturalmente y aclare los bordes entre conceptos relacionados.

## Repos de un solo contexto vs multi-contexto

**Un solo contexto (la mayoría):** Un único `CONTEXT.md` en la raíz del repo.

**Múltiples contextos:** Un `CONTEXT-MAP.md` en la raíz lista los contextos, dónde viven y cómo se relacionan:

```md
# Context Map

## Contextos

- [Ordering](./src/ordering/CONTEXT.md) — recibe y rastrea Orders de Customers
- [Billing](./src/billing/CONTEXT.md) — genera Invoices y procesa pagos
- [Fulfillment](./src/fulfillment/CONTEXT.md) — gestiona picking de almacén y envíos

## Relaciones

- **Ordering → Fulfillment**: Ordering emite eventos `OrderPlaced`; Fulfillment los consume para iniciar picking
- **Fulfillment → Billing**: Fulfillment emite `ShipmentDispatched`; Billing los consume para generar Invoices
- **Ordering ↔ Billing**: Tipos compartidos para `CustomerId` y `Money`
```

La skill infiere la estructura aplicable:

- Si existe `CONTEXT-MAP.md`, léelo para encontrar contextos
- Si sólo existe un `CONTEXT.md` raíz, contexto único
- Si no existe ninguno, crea un `CONTEXT.md` raíz perezosamente cuando se resuelva el primer término

Cuando existen múltiples contextos, infiere a cuál pertenece el tema actual. Si no está claro, pregunta.
