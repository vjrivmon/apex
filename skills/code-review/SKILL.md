# CodeReview — Revision de codigo estilo staff engineer

## Cuando activar

- Despues de cada fase de implementacion (fases 6-8)
- Antes de merge a main
- A peticion del usuario: `/review`
- Automaticamente si hay mas de 5 archivos modificados en un commit

## Objetivo

Revisar codigo como un staff engineer: encontrar bugs reales, violaciones
arquitectonicas, problemas de rendimiento y gaps de testing. Auto-corregir lo
trivial, explicar lo complejo. Evitar bikeshedding sobre estilo.

## Proceso

### Paso 1: Scope del review

Determinar que archivos revisar:

```bash
# Opcion A: cambios desde ultimo commit
git diff --name-only HEAD~1

# Opcion B: cambios en el working tree
git diff --name-only
git diff --name-only --cached

# Opcion C: directorio especifico proporcionado por el usuario
```

Leer TODOS los archivos del scope. No revisar parcialmente.

### Paso 2: Analisis por categoria

Para CADA archivo, verificar las siguientes categorias en orden de prioridad:

#### P0 — Critico (bloquea merge)

**Bugs logicos**

- Variables sin inicializar o usadas antes de asignar
- Condiciones invertidas (if/else al reves)
- Off-by-one errors en loops e indices
- Race conditions en codigo async (await faltante, shared state)
- Null/undefined no manejados en paths criticos
- Division por cero, overflow potencial
- Recursos no cerrados (file handles, DB connections, streams)

**Seguridad**

- Delegar al skill `security-audit` si se detecta algo sospechoso
- SQL injection, XSS, command injection
- Secrets hardcodeados en el codigo
- Permisos excesivos (chmod 777, CORS \*)

**Errores de tipo**

- TypeScript: `any` innecesario, type assertions inseguras (`as`)
- Python: funciones sin type hints en interfaces publicas
- Mismatches entre tipo declarado y tipo real

#### P1 — Alto (deberia arreglarse antes de merge)

**Arquitectura**

- Violaciones de capas hexagonales: infrastructure importando de domain
  directamente, domain importando de infrastructure
- Dependencias circulares entre modulos
- Logica de negocio en controllers/handlers (deberia estar en use cases)
- Acceso directo a BD fuera de repositorios
- Hardcoded values que deberian ser configuracion

**Error handling**

- Exceptions silenciadas (catch vacio, `except: pass`)
- Errores genericos donde deberian ser especificos
- Missing error handling en operaciones I/O (network, filesystem, DB)
- Falta de retry en operaciones que pueden fallar transitoriamente

**Async/Concurrencia**

- `await` faltante en funciones async
- Blocking calls dentro de async context (requests en vez de httpx)
- Shared mutable state sin locks
- Promise/Future no manejados

#### P2 — Medio (mejorar cuando sea posible)

**Performance**

- N+1 queries (loop con query dentro)
- Objetos grandes copiados innecesariamente
- Regex compilado en cada llamada (deberia ser constante)
- Imports pesados en hot paths
- Falta de paginacion en queries que pueden devolver muchos resultados

**Duplicacion**

- Logica duplicada entre funciones (>10 lineas identicas)
- Constantes duplicadas (magic numbers/strings)
- Patrones que deberian extraerse a utilidad compartida

**Testing gaps**

- Funciones publicas nuevas sin tests
- Edge cases no cubiertos (listas vacias, None, strings vacios)
- Mocks que no reflejan el comportamiento real
- Tests que testean la implementacion en vez del comportamiento

#### P3 — Bajo (nice-to-have)

**Legibilidad**

- Nombres de variables poco descriptivos (x, tmp, data2)
- Funciones de >50 lineas que podrian dividirse
- Comentarios obsoletos que no reflejan el codigo actual
- Imports no usados

**Consistencia**

- Mezcla de estilos (snake_case y camelCase en el mismo archivo)
- Patrones inconsistentes entre archivos similares

### Paso 3: Auto-fix de issues triviales

Corregir automaticamente SIN preguntar:

- Imports no usados → eliminar
- Trailing whitespace → eliminar
- Ordenacion de imports (stdlib → third-party → local)
- `pass` en except blocks → al menos `logging.warning`
- Type hints obvios faltantes (return types de funciones simples)
- f-strings vacios → string literal

Informar al usuario de los auto-fixes realizados.

### Paso 4: Generar informe

Formato del output:

````markdown
## Code Review Summary

**Archivos revisados**: N **Auto-fixes aplicados**: N

### Hallazgos

#### [CRITICO] {archivo}:{linea} — {titulo}

{descripcion}

```{lang}
# Problema
{codigo_actual}

# Fix sugerido
{codigo_sugerido}
```
````

#### [ALTO] {archivo}:{linea} — {titulo}

...

#### [MEDIO] {archivo}:{linea} — {titulo}

...

### Auto-fixes aplicados

1. `{archivo}`: {descripcion del fix}
2. ...

### Tests recomendados

Para los cambios revisados, se recomienda anadir tests para:

1. {descripcion del test}
2. ...

````

### Paso 5: Registrar hallazgos criticos en context.db

Para cada hallazgo CRITICO, registrar en context.db:

```python
await db.add_error(
    source="code-review",
    description=f"[{severity}] {titulo} en {archivo}:{linea}",
    lesson=f"Fix: {descripcion_del_fix}",
    phase=current_phase,
    cause=categoria,
    fix=codigo_fix,
    severity="critical" if P0 else "high"
)
````

## Reglas estrictas

1. **NO bikeshedding**: No comentar sobre preferencias de estilo que no afectan
   la funcionalidad (tabs vs spaces, trailing commas, etc.). Si hay un linter
   configurado, eso es responsabilidad del linter.

2. **Bugs reales > estilo**: Priorizar encontrar bugs que causan comportamiento
   incorrecto sobre mejoras cosmeticas. Un bug silencioso es infinitamente peor
   que un nombre de variable feo.

3. **Contexto importa**: Leer el archivo completo antes de reportar. Muchos
   "problemas" se explican con el contexto circundante. Un `# type: ignore`
   puede estar justificado.

4. **Fix concreto obligatorio**: Cada hallazgo P0/P1 DEBE incluir el codigo del
   fix, no solo la descripcion del problema.

5. **Agrupar por archivo**: No reportar el mismo patron 10 veces. Indicar "mismo
   patron en lineas X, Y, Z" y dar un solo fix.

6. **Respetar la arquitectura declarada**: Leer CLAUDE.md y context.db para
   entender la arquitectura del proyecto. No sugerir cambios que la contradigan.

7. **No crear issues fantasma**: Si el codigo es correcto y claro, decir "LGTM"
   o "Sin hallazgos criticos". No inventar problemas para justificar el review.

## Ejemplo de review bien hecho

````markdown
## Code Review: backend/application/api.py

### [CRITICO] L145 — await faltante en llamada async

La funcion `scrape_products` llama a `scraper.search(query)` sin await. Esto
retorna una coroutine sin ejecutarla, haciendo que el endpoint siempre devuelva
una lista vacia.

```python
# ANTES (bug)
results = scraper.search(query)  # Returns coroutine, not results

# DESPUES (fix)
results = await scraper.search(query)
```
````

### [ALTO] L89-120 — Logica de negocio en el handler

El calculo de presupuesto (30 lineas) deberia estar en `core/agents/budget.py`,
no en el endpoint. Viola la arquitectura hexagonal: el handler solo deberia
orquestar, no calcular.

### Auto-fixes aplicados

1. `api.py`: Eliminados 3 imports no usados (json, os, sys)
2. `api.py`: Anadido type hint `-> list[ProductDTO]` a `get_products`

````

## Ejemplo de review incorrecto (evitar)

```markdown
# MAL — bikeshedding
### [BAJO] L12 — Deberia usar f-string en vez de .format()
# Esto no afecta la funcionalidad. Si no hay linter rule, no reportar.

# MAL — sin fix
### [CRITICO] L145 — Hay un bug aqui
# Reportar un critico sin explicar el fix es inutil.

# MAL — falso positivo
### [ALTO] L30 — Variable `data` podria ser None
# Verificar antes: si hay un guard clause en L28, no es un hallazgo.
````
