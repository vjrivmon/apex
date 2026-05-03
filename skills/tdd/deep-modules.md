# Deep Modules

De "A Philosophy of Software Design" (Ousterhout):

**Deep module** = interface pequeña + mucha implementación

```
┌─────────────────────┐
│   Interface pequeña │  ← Pocos métodos, params simples
├─────────────────────┤
│                     │
│                     │
│ Implementación      │  ← Lógica compleja oculta
│ profunda            │
│                     │
└─────────────────────┘
```

**Shallow module** = interface grande + poca implementación (evitar)

```
┌─────────────────────────────────┐
│       Interface grande          │  ← Muchos métodos, params complejos
├─────────────────────────────────┤
│  Implementación delgada         │  ← Sólo pasa por encima
└─────────────────────────────────┘
```

Al diseñar interfaces, pregunta:

- ¿Puedo reducir el número de métodos?
- ¿Puedo simplificar los params?
- ¿Puedo ocultar más complejidad dentro?
