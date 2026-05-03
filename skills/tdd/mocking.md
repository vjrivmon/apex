# Cuándo mockear

Mockea sólo en **bordes del sistema**:

- APIs externas (pago, email, etc.)
- Bases de datos (a veces — prefiere DB de test)
- Tiempo / aleatoriedad
- Sistema de archivos (a veces)

No mockees:

- Tus propias clases/módulos
- Colaboradores internos
- Cualquier cosa que controles

## Diseñar para mockabilidad

En los bordes del sistema, diseña interfaces fáciles de mockear:

**1. Inyección de dependencias**

Pasa las dependencias externas en lugar de crearlas internamente:

```typescript
// Fácil de mockear
function processPayment(order, paymentClient) {
  return paymentClient.charge(order.total);
}

// Difícil de mockear
function processPayment(order) {
  const client = new StripeClient(process.env.STRIPE_KEY);
  return client.charge(order.total);
}
```

**2. Prefiere interfaces estilo SDK sobre fetchers genéricos**

Crea funciones específicas para cada operación externa en lugar de una función genérica con lógica condicional:

```typescript
// BIEN: Cada función mockea independientemente
const api = {
  getUser: (id) => fetch(`/users/${id}`),
  getOrders: (userId) => fetch(`/users/${userId}/orders`),
  createOrder: (data) => fetch('/orders', { method: 'POST', body: data }),
};

// MAL: Mockear requiere lógica condicional dentro del mock
const api = {
  fetch: (endpoint, options) => fetch(endpoint, options),
};
```

La aproximación SDK significa:
- Cada mock devuelve una forma específica
- Sin lógica condicional en el setup del test
- Es más fácil ver qué endpoints ejercita cada test
- Type-safety por endpoint
