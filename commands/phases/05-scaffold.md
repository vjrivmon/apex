# Fase 5 — Scaffold

Crear estructura sin logica. Solo esqueleto. **Git inicializado obligatorio
ANTES de escribir codigo** (lección focusnow#4).

## Gate de entrada (OBLIGATORIO antes del sub-paso [5a])

```
apex_phase_entry_check(phase=5, context_hint="<nombre-del-proyecto o feature>")
```

Lee el bloque `### Lecciones cross-project aplicadas` que devuelve y **cita
explícitamente** en el siguiente mensaje qué errores previos aplican a este
proyecto. Si el bloque dice "0 hits", escríbelo también. No continuar sin
haber citado el bloque.

**Queries que ejecuta internamente**: "scaffold hexagonal estructura errores",
"git init secretos env". Añade `context_hint` con el stack concreto (ej:
`"FastAPI + Next.js"`) para retrieval más preciso.

## Sub-pasos en orden

- **[5a]** **Git init OBLIGATORIO** antes que cualquier otra cosa:
  ```
  git init
  echo ".env\n.venv/\nnode_modules/\ndist/\n.apex/" > .gitignore
  git add .gitignore && git commit -m "chore: scaffold inicial"
  ```
  Sin git, el resto de la fase no puede continuar. El grader bloquea el
  cierre de fase si `.git/` no existe.
- **[5b]** Crear estructura de directorios segun la arquitectura de fase 2.
  Siempre hexagonal: `domain/`, `ports/`, `adapters/`, `application/`,
  `shared/`. Nunca monolitico.
- **[5c]** Configurar dependencias: package.json / requirements.txt /
  pyproject.toml. Instalar y verificar que no hay conflictos.
- **[5d]** Configurar linter, formatter, y TypeScript strict si aplica.
- **[5e]** Crear .env.example con todas las variables necesarias (sin valores
  reales).
- **[5f]** Crear archivos base vacios con imports y exports para que la
  estructura compile sin errores.
- **[5g]** Verificar que `npm run build` / `python -m py_compile` pasa sin
  errores.
- **[5h]** Registrar componentes con `apex_add_component`.
- **[5i-sec]** Verificar que `.env` esta en `.gitignore` ANTES del primer commit.
  Ejecutar `grep -r "password\|secret\|api_key\|token" . --include="*.py" --include="*.ts" --include="*.js" -l | grep -v ".env.example" | grep -v ".gitignore"`.
  Si hay hits: corregir antes de continuar. Secretos en repo = bloqueo de fase.
- **[5i]** Conventional commit del scaffold completo (`feat: scaffold
  hexagonal con linter y .env.example`).
- **[5j]** Ejecutar `apex_grader_evaluate(phase=5, mode="deterministic")`.
  El grader verifica: `git_initialized` (bloqueante).
- **[5k]** Si verdict pasa: `apex_set_phase(phase_number=5, status="completed")`.
  El handler MCP rechaza la transición si el grader bloqueó.

## Criterio de salida (outcome-based)

- `.git/` existe y al menos un commit registrado.
- Directorios hexagonales creados.
- Build limpio (`npm run build` o `python -m py_compile`).
- .env.example con variables documentadas.
- Linter + formatter configurados.
- Verdict del grader: `should_block=false`.
- Fase marcada como `completed` en context.db (sólo si verdict pasa).
