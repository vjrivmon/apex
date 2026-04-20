# DevOps — CI/CD, Docker multi-stage, rollback automation

## Cuándo activar

- **Fase 5 (Scaffold)**: si el proyecto tendrá deploy, scaffolear CI
  desde el principio. Regla cross-project recurrente: "git init + primer
  commit + CI funcional son parte de fase 5, no de fase 11".
- **Fase 11 (Deploy)**: consolidar deploy automatizado con rollback < 5 min.
- **Fase 13 (Escalado)**: si el tráfico lo justifica, añadir staging
  intermedio + blue/green.
- **On-demand**: cuando el usuario pide "CI", "pipeline", "docker",
  "deploy", "rollback", "GitHub Actions".

## Objetivo

Producir un pipeline CI/CD **templatizado**, reutilizable en todos los
proyectos de Vicente, que:

- Corre tests + lint + build en cada PR.
- Builda imagen Docker multi-stage con cache.
- Despliega a staging automáticamente desde `main`.
- Despliega a prod solo con tag `v*.*.*` firmado.
- Rollback en <5 min vía `git revert` + redeploy automático.

## Principios absolutos

1. **Conventional commits** (feat/fix/refactor/docs/chore/test/build/ci/perf).
2. **Trunk-based**: `main` siempre deployable. No long-lived branches.
3. **PRs pequeñas**: ≤400 LOC de cambio. Si más → split.
4. **No secrets en repo**. Todo en GitHub Secrets / Vercel env / .env local.
5. **Rollback es primer ciudadano**: todo deploy debe tener un botón de
   rollback explícito documentado en `releases/published/<version>/rollback-plan.md`.
6. **Docker multi-stage**: separar build deps de runtime. Target < 200 MB.
7. **Healthcheck obligatorio**: cada servicio expone `/health` con 3
   checks (DB, externals, disk). Ver skill `monitor`.
8. **Release notes auto-generadas**: por conventional commits (release-please).

## Uso típico

```
apex_scaffold_devops(target_dir="/path/proyecto", stack="python", with_monitoring=True)
```

Copia los templates `apex/templates/{.github,docker,monitor}/*` al
proyecto renombrando placeholders:

- `{{PROJECT_NAME}}` → nombre del proyecto
- `{{STACK}}` → python | node
- `{{DEPLOY_TARGET}}` → vercel | fly | vps
- `{{HEALTH_PATH}}` → /health (default)

## Templates incluidos

- `.github/workflows/ci.yml` — test + lint + build en cada PR.
- `.github/workflows/deploy-staging.yml` — push a `main` → staging.
- `.github/workflows/deploy-prod.yml` — tag `v*.*.*` → prod.
- `.github/workflows/release-please.yml` — changelog + tagging auto.
- `docker/Dockerfile` — multi-stage (builder + runtime).
- `docker/docker-compose.prod.yml` — stack completo con healthcheck.
- `.releaserc.json` — semver config.

## Rollback playbook

Cuando algo va mal en prod:

```bash
# 1. Identificar el último tag bueno
git tag -l "v*" | tail -5

# 2. Revertir el merge a main
git revert -m 1 <merge-sha>
git push origin main          # dispara deploy-staging automático

# 3. Re-tagger el release anterior en prod si el staging falla
git tag -s v1.2.3-rollback -m "rollback from v1.2.4"
git push origin v1.2.3-rollback

# 4. Publicar incident report en releases/published/incidents/
```

## Regla cross-project (OBLIGATORIA)

Antes de arrancar un pipeline nuevo:

```
apex_search_cross_project(query="deploy ci docker rollback")
```

Reutiliza patrones ya validados en otros proyectos (ej. el template
Docker multi-stage refinado en DNI-v4.0).
