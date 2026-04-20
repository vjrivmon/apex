# Fase 5 — Scaffold

Crear estructura sin logica. Solo esqueleto.

## Sub-pasos en orden

- **[5a]** Crear estructura de directorios segun la arquitectura de fase 2.
  Siempre hexagonal: `domain/`, `ports/`, `adapters/`, `application/`,
  `shared/`. Nunca monolitico.
- **[5b]** Configurar dependencias: package.json / requirements.txt /
  pyproject.toml. Instalar y verificar que no hay conflictos.
- **[5c]** Configurar linter, formatter, y TypeScript strict si aplica.
- **[5d]** Crear .env.example con todas las variables necesarias (sin valores
  reales).
- **[5e]** Crear archivos base vacios con imports y exports para que la
  estructura compile sin errores.
- **[5f]** Verificar que `npm run build` / `python -m py_compile` pasa sin
  errores.
- **[5g]** Registrar componentes con `apex_add_component`.
- **[5h]** `apex_set_phase(phase_number=5, status="completed")`.

## Criterio de salida

- Directorios hexagonales creados.
- Build limpio (`npm run build` o `python -m py_compile`).
- .env.example con variables documentadas.
- Linter + formatter configurados.
- Fase marcada como `completed` en context.db.
