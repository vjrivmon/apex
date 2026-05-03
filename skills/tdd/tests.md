# Tests buenos y malos

## Buenos tests

**Estilo integración**: Testea a través de interfaces reales, no de mocks de partes internas.

```typescript
// BIEN: Testea comportamiento observable
test("user can checkout with valid cart", async () => {
  const cart = createCart();
  cart.add(product);
  const result = await checkout(cart, paymentMethod);
  expect(result.status).toBe("confirmed");
});
```

Características:

- Testea comportamiento que les importa a usuarios/callers
- Usa sólo API pública
- Sobrevive a refactors internos
- Describe QUÉ, no CÓMO
- Una aserción lógica por test

## Malos tests

**Tests de detalles de implementación**: Acoplados a la estructura interna.

```typescript
// MAL: Testea detalles de implementación
test("checkout calls paymentService.process", async () => {
  const mockPayment = jest.mock(paymentService);
  await checkout(cart, payment);
  expect(mockPayment.process).toHaveBeenCalledWith(cart.total);
});
```

Banderas rojas:

- Mockear colaboradores internos
- Testear métodos privados
- Aserciones sobre número/orden de llamadas
- El test rompe al refactorizar sin cambio de comportamiento
- El nombre describe CÓMO no QUÉ
- Verificación por medios externos en vez de la interface

```typescript
// MAL: Esquiva la interface para verificar
test("createUser saves to database", async () => {
  await createUser({ name: "Alice" });
  const row = await db.query("SELECT * FROM users WHERE name = ?", ["Alice"]);
  expect(row).toBeDefined();
});

// BIEN: Verifica a través de la interface
test("createUser makes user retrievable", async () => {
  const user = await createUser({ name: "Alice" });
  const retrieved = await getUser(user.id);
  expect(retrieved.name).toBe("Alice");
});
```
