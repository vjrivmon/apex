# Onboard Existing Project — Integrar proyecto existente en APEX

## Cuándo activar

Cuando el usuario invoca /apex en un directorio que tiene código pero NO tiene
.apex/.

## Objetivo

Analizar el repositorio existente, detectar automáticamente en qué fases ya
está, crear .apex/context.db con el estado real, y proponer qué falta.

## Flujo

### Paso 1: Análisis del repositorio

```bash
# Git history
git log --oneline -20
git log --format="%H %s" --since="1 month ago" | head -20

# Estructura
find . -type f -name "*.py" -o -name "*.ts" -o -name "*.tsx" -o -name "*.js" | head -50
ls -la

# Dependencias
cat package.json 2>/dev/null | head -20
cat requirements.txt 2>/dev/null
cat pyproject.toml 2>/dev/null | head -30

# Tests
ls tests/ test/ __tests__/ spec/ 2>/dev/null
find . -name "test_*.py" -o -name "*.test.ts" -o -name "*.spec.ts" 2>/dev/null | head -20

# Docs
cat README.md 2>/dev/null | head -30
cat CLAUDE.md 2>/dev/null | head -30
ls docs/ 2>/dev/null

# Config
cat .env.example 2>/dev/null
cat docker-compose.yml 2>/dev/null | head -20
cat .github/workflows/*.yml 2>/dev/null | head -20
```

### Paso 2: Detección automática de fases

| Señal detectada                   | Fase completada             |
| --------------------------------- | --------------------------- |
| Tiene SPEC.md o similar           | Fase 3 (spec)               |
| Tiene domain/, entities/, models/ | Fase 6 (core)               |
| Tiene infrastructure/, adapters/  | Fase 7 (infra)              |
| Tiene tests con >0 pasando        | Fase 9 (testing parcial)    |
| Tiene Dockerfile o docker-compose | Fase 11 (deploy parcial)    |
| Tiene .github/workflows/          | Fase 11 (CI/CD)             |
| Tiene EDGE-CASES.md               | Fase 4 (edge cases)         |
| Tiene README.md completo          | Documentación presente      |
| Tiene .env.example + .gitignore   | Fase 5 (scaffold)           |
| Tiene auth/security middleware    | Fase 10 (seguridad parcial) |

### Paso 3: Crear .apex/

```
mcp__apex__apex_init_project(name="...", description="Proyecto existente onboarded")
```

Marcar fases detectadas como completadas:

```
mcp__apex__apex_set_phase(phase_number=X, status="completed", notes="Detectado automáticamente: ...")
```

Registrar componentes encontrados:

```
mcp__apex__apex_add_component(id="...", name="...", type="...", status="implemented")
```

### Paso 4: Presentar resumen al usuario

```
Proyecto analizado: [nombre]
- X commits, Y archivos, Z tests
- Fases detectadas como completadas: [lista]
- Fases que faltan: [lista]
- Próximos pasos recomendados: [lista]
```

### Paso 5: Preguntar al usuario si el análisis es correcto

Solo aquí se pregunta. Si hay fases que el análisis marcó incorrectamente, el
usuario corrige y se actualiza context.db.

## Reglas

- NO asumir nada que no se pueda detectar del código
- Si hay duda sobre una fase, marcarla como "partial" en las notes
- Registrar la decisión de onboarding: "Proyecto existente integrado en APEX"
- Los errores pasados del proyecto NO se pueden detectar — empezar en limpio
