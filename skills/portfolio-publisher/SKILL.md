---
name: portfolio-publisher
description: Publica un proyecto terminado como caso real en vr-web/content/cases/ al cerrar la fase 14 de /apex, con aprobación manual intermedia. Usar cuando el usuario pide sacarlo al portfolio. Triggers ES/EN — portfolio, publicar caso, publícalo, añadir a casos, vr-web, publish case.
---

# PortfolioPublisher — Publica el proyecto en vr-web/content/cases/

## Cuándo activar

- Al completar la **fase 14** (Mantenimiento) de un proyecto: candidato
  natural a aparecer en "Casos reales" del funnel.
- Cuando el usuario pide explícitamente: "publícalo en el portfolio",
  "añádelo a casos", "sácalo a vr-web".
- Tras un cambio significativo en un caso ya publicado (nueva métrica, nuevo
  learning): regeneración del MDX con merge.

## Flujo (dos pasos, con aprobación manual intermedia)

### Paso 1 — Preparar campos en context.db

Antes de generar el draft, asegúrate de que el `project_meta` contiene los
campos `portfolio_*`. Si faltan, guíalos con preguntas cerradas al usuario
y guárdalos con `apex_set_portfolio_meta`:

- `portfolio_title` — nombre público (ej. "DNI Valencia v4.0")
- `portfolio_client` — cliente/contexto (ej. "DNI Valencia (ONG)")
- `portfolio_duration` — "18 meses (v1.0 → v4.0)"
- `portfolio_stack` — "Python, FastAPI, ChromaDB, Ollama"
- `portfolio_status` — "En producción" / "En uso diario" / "En desarrollo"
- `portfolio_headline` — una frase con métrica principal
- `portfolio_context` — 1-2 párrafos de introducción
- `portfolio_problem` — 1-2 párrafos del dolor concreto
- `portfolio_approach` — 2-3 párrafos de cómo se resolvió
- `portfolio_constraints` — lista de strings
- `portfolio_results` — lista de `{metric, value}`
- `portfolio_learnings` — lista de strings (lo que te llevas de este caso)
- `portfolio_related_pack` — `citadel` | `compass` | `forge`
- `portfolio_related_pack_cta` — una frase invitando al pack
- `portfolio_repo_url`, `portfolio_demo_url` — opcionales
- `portfolio_tags` — array de etiquetas cortas
- `portfolio_built_with_apex` — bool (default true)

### Paso 2 — Generar draft y esperar aprobación

Ejecuta la tool MCP:

```
apex_portfolio_draft(slug="<slug>", apply=False)
```

Esto produce `~/RoadToDevOps/vr-web/content/cases/<slug>.mdx.draft`. Muestra
el contenido generado al usuario, con diff respecto al `.mdx` existente si
lo hubiera.

**No avances sin el visto bueno explícito del usuario.**

### Paso 3 — Aplicar y commitear

Tras aprobación del usuario:

1. `apex_portfolio_draft(slug="<slug>", apply=True)` — sobreescribe el
   `.mdx` final (con merge preservando campos manuales).
2. `cd ~/RoadToDevOps/vr-web` y:
   ```bash
   git add content/cases/<slug>.mdx
   git commit -m "feat(cases): publica <slug> desde APEX"
   git push
   ```
3. Vercel redeploya automáticamente al push.
4. Borrar el `.mdx.draft` si existía.

## Regla cross-project (recomendada)

Antes de decidir el framing (headline, métricas destacadas), ejecuta:

```
apex_search_cross_project(query="<dominio del caso>")
```

Busca cómo se presentó un caso similar en otro proyecto para mantener
coherencia editorial en todos los casos del portfolio.

## Output esperado

- `content/cases/<slug>.mdx` con frontmatter YAML completo (schema
  CaseStudy de vr-web).
- `apex_log_session` registrando la publicación y link al commit.
- El caso aparece automáticamente en la home de vr-web (sección "Casos
  reales") y en `/caso/<slug>` tras el redeploy.
