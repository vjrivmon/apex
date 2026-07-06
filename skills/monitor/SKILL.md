---
name: monitor
description: Establece observabilidad (health extendido, logs agregados, Prometheus/Grafana, SLOs, alertas) antes del primer deploy en fase 11 y en escalado/mantenimiento (13-14) de /apex. Triggers ES/EN — monitor, observabilidad, health, monitoring, alertas, SLO, dashboard, observability.
---

# Monitor — Observabilidad que alerta antes de que se rompa

## Cuándo activar

- **Fase 11 (Deploy)**: antes del primer deploy a prod, debe existir
  `/health` extendido, logs agregados y una alerta mínima.
- **Fase 13 (Escalado)**: consolidar Prometheus + Grafana con SLOs.
- **Fase 14 (Mantenimiento)**: runbooks por alerta.
- **On-demand**: cuando el usuario pide "health", "monitoring",
  "dashboard", "alertas", "SLO", "observability".

## Objetivo

Que el sistema detecte problemas **antes** que el usuario. Alertas
prioritizadas por impacto, no por volumen. Cero alertas en prime time a
menos que alguien tenga que actuar en <5 min.

## Niveles de observabilidad (aplicar en orden)

1. **Nivel 0 — /health** (siempre, desde fase 11):
   - DB reachable
   - External services reachable
   - Disk usage < 80%
   - Uptime + versión
   - Tiempo de respuesta < 50 ms

2. **Nivel 1 — Métricas básicas** (desde fase 13):
   - Latencia p50/p95/p99 por endpoint
   - Error rate 4xx/5xx por endpoint
   - Throughput (req/s)
   - Resource usage (CPU/RAM/disk)

3. **Nivel 2 — Logs estructurados** (desde fase 13):
   - JSON logs con request_id
   - Niveles: DEBUG / INFO / WARN / ERROR / FATAL
   - Redacción de secrets (ver skill `security-audit`)

4. **Nivel 3 — Trazas distribuidas** (solo si hay microservicios):
   - OpenTelemetry → Tempo / Jaeger
   - Span por request + correlación cross-service

5. **Nivel 4 — SLOs + error budget** (prod maduro):
   - Availability SLO: 99.9% (error budget = 43 min/mes)
   - Latency SLO: p95 < 300 ms
   - Alertas de burn rate

## Reglas de alertas

1. **Una alerta = una acción**. Si no hay acción, no es alerta, es
   dashboard.
2. **Severidad con criterio**:
   - `critical`: usuario afectado, pagar ahora (siempre <5 min).
   - `warning`: degradación sin impacto, actuar hoy.
   - `info`: telemetría, no despierta a nadie.
3. **Runbook por alerta**: cada alerta enlaza a un `.md` con "qué hacer
   en los próximos 10 minutos". Sin runbook, no se produciliza.
4. **Test de las alertas**: al menos una vez al mes, trigger una alerta
   manualmente para validar el pipeline (chaos monkey ligero).

## Templates incluidos

- `templates/monitor/health.py.example` — endpoint FastAPI completo
  con DB + externals + disk + version.
- `templates/monitor/prometheus.yml` — scrape config por defecto.
- `templates/monitor/grafana-dashboard.json` — dashboard con las 4
  métricas core (latencia, errores, throughput, saturación = USE).
- `templates/monitor/alerts.yml` — reglas Prometheus con 5 alertas
  base (latency p95, error rate, disk, uptime, DB connection).
- `templates/monitor/loki-config.yml` — agregador de logs.

## Regla cross-project (OBLIGATORIA)

Consultar `apex_search_cross_project` con "monitor", "health", "alerta"
antes de montar el stack. Reusar dashboards/alertas validados en
proyectos previos ahorra días de tuning de umbrales.

## Protocolo de verificación antes de Deploy (fase 11)

- [ ] `/health` responde 200 con JSON que incluye: `status`, `version`,
      `uptime_seconds`, `checks` (dict con DB + externals + disk).
- [ ] `/health` falla (status 503) si cualquier check falla.
- [ ] Logs son JSON, tienen `request_id` y no contienen secrets.
- [ ] Mínimo 1 alerta configurada: `HealthcheckFailing` → critical.
- [ ] Runbook escrito para la alerta anterior.
