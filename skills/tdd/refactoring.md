# Candidatos de refactor

Tras el ciclo TDD, busca:

- **Duplicación** → Extraer función/clase
- **Métodos largos** → Romper en helpers privados (mantén tests sobre la interface pública)
- **Shallow modules** → Combinar o profundizar
- **Feature envy** → Mover la lógica donde vive el dato
- **Primitive obsession** → Introducir value objects
- **Código existente** que el código nuevo revela como problemático
