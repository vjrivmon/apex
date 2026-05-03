# Diseño de interfaces para testabilidad

Las buenas interfaces hacen que testear sea natural:

1. **Acepta dependencias, no las crees**

   ```typescript
   // Testeable
   function processOrder(order, paymentGateway) {}

   // Difícil de testear
   function processOrder(order) {
     const gateway = new StripeGateway();
   }
   ```

2. **Devuelve resultados, no produzcas efectos secundarios**

   ```typescript
   // Testeable
   function calculateDiscount(cart): Discount {}

   // Difícil de testear
   function applyDiscount(cart): void {
     cart.total -= discount;
   }
   ```

3. **Superficie pequeña**
   - Menos métodos = menos tests necesarios
   - Menos params = setup de test más simple
