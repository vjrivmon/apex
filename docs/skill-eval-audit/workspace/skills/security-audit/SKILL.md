---
name: security-audit
description: "Auditoría de seguridad con OWASP Top 10 (2021), threat model STRIDE, AgentArmor 8 capas y OWASP ASI Top-10. Solo reporta hallazgos con confianza mayor o igual a 8/10, cada P0/P1 con fix concreto en código, agrupa patrones repetidos, ajusta severidad por contexto (dev vs prod, personal vs SaaS). Produce SECURITY-AUDIT.md. Usar en fase de seguridad, antes de deploy, o al añadir endpoints o auth. Triggers ES/EN — security audit, auditoría de seguridad, /security audit, OWASP, STRIDE."
---

# SecurityAudit — Auditoría automatizada + AgentArmor 8-layer + ASI Top-10

> **Ampliado en Sprint 6**: integra el modelo **AgentArmor** (8 capas de
> seguridad distribuidas por las fases de APEX) + cobertura **OWASP ASI
> Top-10** (agentic system threats). La sub-fase **10.5** ejecuta el
> `apex_security_gate` antes de permitir fase 11 (Deploy): falla si
> cualquier capa L1–L8 no tiene evidencia verificable.

## Cuando activar

- Fase 10 (seguridad) del flujo APEX
- Sub-fase **10.5 (Security Gate)** — gate obligatorio antes de fase 11
- Antes de cualquier deploy a produccion
- Cuando se anade un nuevo endpoint o se modifica autenticacion
- Cuando se añade un nuevo agente/tool al sistema (MCP, sub-agentes)
- A peticion del usuario: `/security:audit`

## Objetivo

Realizar una auditoria de seguridad completa del proyecto, combinando analisis
estatico de codigo con threat modeling STRIDE. Solo reportar hallazgos con
confianza >= 8/10 para evitar falsos positivos que erosionan la confianza.

## Proceso

### Paso 1: Inventario de superficie de ataque

1. Listar TODOS los endpoints de la API (buscar decoradores `@app.get`,
   `@app.post`, `@router.*`, rutas Express, etc.)
2. Listar TODOS los formularios y puntos de entrada de datos del usuario
3. Identificar flujos de datos: usuario -> frontend -> API -> base de datos
4. Identificar dependencias externas (APIs de terceros, CDNs, paquetes)

### Paso 2: OWASP Top 10 (2021) checklist

Para CADA endpoint y punto de entrada, verificar:

| #   | Vulnerabilidad            | Que buscar                                                                                                                                                                   |
| --- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A01 | Broken Access Control     | Endpoints sin auth middleware, IDOR (IDs predecibles), falta de RBAC, acceso directo a recursos ajenos                                                                       |
| A02 | Cryptographic Failures    | Secretos en codigo/logs, HTTP sin TLS, hashing debil (MD5/SHA1 para passwords), tokens predecibles                                                                           |
| A03 | Injection                 | SQL injection (string concatenation en queries, especialmente SQLite), XSS (user input reflejado sin escapar), command injection (subprocess con shell=True), path traversal |
| A04 | Insecure Design           | Falta de rate limiting, logica de negocio bypasseable, sin validacion server-side                                                                                            |
| A05 | Security Misconfiguration | CORS con `*`, debug mode en produccion, headers de seguridad faltantes (CSP, HSTS, X-Frame-Options), .env en git                                                             |
| A06 | Vulnerable Components     | Dependencias con CVEs conocidos (comprobar con `pip audit` / `npm audit`)                                                                                                    |
| A07 | Auth Failures             | Falta de auth, sesiones sin expiracion, tokens JWT sin validar, passwords en plaintext                                                                                       |
| A08 | Data Integrity Failures   | Deserializacion insegura, falta de verificacion de integridad en updates                                                                                                     |
| A09 | Logging Failures          | Sin audit log, datos sensibles en logs (passwords, tokens, datos personales)                                                                                                 |
| A10 | SSRF                      | Fetch de URLs controladas por usuario sin whitelist, redirect abiertos                                                                                                       |

### Paso 3: STRIDE Threat Model

Para cada componente del sistema, evaluar las 6 amenazas:

**S — Spoofing (Suplantacion)**

- Puede alguien hacerse pasar por otro usuario?
- Los tokens/sesiones son verificables y no falsificables?
- Hay autenticacion en todos los flujos que lo requieren?

**T — Tampering (Manipulacion)**

- Se pueden modificar datos en transito? (HTTPS?)
- Se valida la integridad de los datos en el servidor?
- Se puede manipular el request para cambiar el comportamiento?

**R — Repudiation (No repudio)**

- Se puede negar haber realizado una accion?
- Hay audit log de acciones criticas (compras, cambios de config)?
- Los logs son inmutables?

**I — Information Disclosure (Fuga de informacion)**

- Que datos se exponen en las respuestas de error?
- Los stack traces se muestran al usuario?
- Hay datos sensibles en localStorage/cookies sin cifrar?
- Las respuestas de la API incluyen mas datos de los necesarios?

**D — Denial of Service (Denegacion de servicio)**

- Hay rate limiting en endpoints publicos?
- Se puede saturar con requests pesados (scraping, LLM calls)?
- Las queries SQL estan limitadas (LIMIT, timeout)?
- Hay proteccion contra uploads masivos?

**E — Elevation of Privilege (Escalada de privilegios)**

- Un usuario normal puede acceder a funciones admin?
- Se puede modificar el rol en el request?
- Los permisos se verifican server-side (no solo en el frontend)?

### Paso 4: Analisis de dependencias

```bash
# Python
pip audit 2>/dev/null || echo "pip-audit no instalado"
pip list --outdated 2>/dev/null

# Node.js
npm audit 2>/dev/null || echo "No es proyecto Node"
```

### Paso 5: Generar informe

Crear `SECURITY-AUDIT.md` en la raiz del proyecto con este formato:

````markdown
# Security Audit Report

**Proyecto**: {nombre} **Fecha**: {fecha} **Auditor**: Claude (APEX
SecurityAudit skill) **Confianza minima reportada**: 8/10

## Resumen Ejecutivo

- Criticos: N
- Altos: N
- Medios: N
- Bajos: N

## Hallazgos

### [CRITICO] {titulo}

- **Categoria**: OWASP A0X / STRIDE-{letra}
- **Ubicacion**: `archivo:linea`
- **Confianza**: X/10
- **Descripcion**: ...
- **Impacto**: ...
- **Fix recomendado**:
  ```python
  # codigo del fix
  ```
````

(repetir para cada hallazgo)

## Dependencias

| Paquete | Version | CVE | Severidad |
| ------- | ------- | --- | --------- |

## Recomendaciones Generales

1. ...
2. ...

## Checklist de Seguridad

- [ ] Rate limiting en todos los endpoints publicos
- [ ] CORS restringido a dominios conocidos
- [ ] Input validation server-side en todos los endpoints
- [ ] Auth middleware en endpoints protegidos
- [ ] Secrets en variables de entorno (no en codigo)
- [ ] HTTPS forzado
- [ ] Headers de seguridad configurados
- [ ] Logging de acciones criticas
- [ ] Dependencias actualizadas
- [ ] Datos sensibles no expuestos en responses

````

### Paso 6: Registrar en context.db

Para cada hallazgo CRITICO, registrar un error:

```python
await db.add_error(
    source="security-audit",
    description=f"[{severity}] {titulo}",
    lesson=fix_recomendado,
    phase=10,
    cause=categoria_owasp,
    fix=codigo_fix,
    severity=severity
)
````

## Reglas estrictas

1. **Confianza >= 8/10**: NO reportar hallazgos con confianza menor. Un falso
   positivo es peor que un falso negativo en este contexto porque erosiona la
   confianza del desarrollador en la herramienta.

2. **Verificar antes de reportar**: Si un hallazgo depende de como se usa (ej:
   CORS con `*` puede ser correcto en desarrollo), indicar el contexto y no
   marcarlo como critico.

3. **Priorizar fixes accionables**: Cada hallazgo DEBE incluir un fix concreto
   con codigo. "Mejorar la seguridad" no es un fix valido.

4. **No duplicar**: Si un patron inseguro se repite en 10 endpoints, reportar
   UNA vez con la lista de endpoints afectados.

5. **Considerar el contexto**: Un proyecto personal sin auth publica tiene
   diferente perfil de riesgo que un SaaS. Ajustar severidades en consecuencia.

## Ejemplo de hallazgo bien reportado

````markdown
### [ALTO] SQL Injection en endpoint /api/products/search

- **Categoria**: OWASP A03 (Injection)
- **Ubicacion**: `backend/application/api.py:145`
- **Confianza**: 9/10
- **Descripcion**: El parametro `query` se concatena directamente en la query
  SQL sin parametrizar: `f"SELECT * FROM products WHERE name LIKE '%{query}%'"`.
  Un atacante puede inyectar SQL arbitrario.
- **Impacto**: Lectura/modificacion/borrado de toda la base de datos.
- **Fix recomendado**:

  ```python
  # ANTES (vulnerable)
  cursor.execute(f"SELECT * FROM products WHERE name LIKE '%{query}%'")

  # DESPUES (seguro)
  cursor.execute("SELECT * FROM products WHERE name LIKE ?", (f"%{query}%",))
  ```
````

```

## Ejemplo de hallazgo bien descartado

```

# DESCARTADO: CORS con localhost:3000

# Confianza: 4/10 — Es entorno de desarrollo, no produccion.

# Si se deployara asi, seria un hallazgo MEDIO.

```

```

---

## AgentArmor — 8 capas distribuidas por fases APEX

Cada capa tiene requisitos de **evidencia** (archivos en `.apex/security/`
con frontmatter `status: passed|pending|failed`). El security gate
(`apex_security_gate`) verifica que **todas** están en `passed` antes de
permitir fase 11.

### L1 — Ingestion (Fases 0, 3)

Protege: inputs del usuario, fuentes externas cargadas al agente.

- **OWASP ASI01 (Goal Hijacking) · ASI04 (Supply Chain)**
- Input scanning y prompt-injection detection.
- Verificación de origen de fuentes (hash, signature).
- MCP scanner: cada MCP nuevo se audita antes de conectar.
- Rate limiting por usuario y por tipo de input.
- Evidencia: `.apex/security/L1-ingestion.md` — checklist + registro
  de MCPs auditados.

### L2 — Storage (Fase 7)

Protege: context.db, memoria persistente, secrets.

- **OWASP ASI06 (Memory Poisoning)**
- AES-256-GCM at rest para datos sensibles.
- HMAC de integridad en snapshots de memoria.
- Tamper detection: hash comparison en startup.
- Secrets nunca en repo, siempre en env/secrets manager.
- Evidencia: `.apex/security/L2-storage.md` — cifrado, HMAC,
  ubicación de secrets.

### L3 — Context (Fases 3, 6)

Protege: prompts del sistema, identity anchoring.

- **OWASP ASI01 (Goal Hijacking) · ASI06 (Memory Poisoning)**
- **GoalLock**: system prompt con canary tokens que, si cambian,
  disparan alerta (inyección detectada).
- Multi-canary: 3+ tokens distribuidos en prompt.
- Template injection stripping en inputs del usuario.
- Evidencia: `.apex/security/L3-context.md` — canarios + mecanismo
  de verificación.

### L4 — Planning (Fase 4)

Protege: decision-making del agente, chain de tool calls.

- **OWASP ASI02 (Tool Misuse) · ASI05 (Code Execution) · ASI08 (Cascading Failures)**
- Action chain tracking: log de cada tool call con contexto.
- Semantic risk scoring: classificar cada acción por riesgo (read/
  write/exec/external-call).
- Multi-step attack detection: heurísticas para secuencias sospechosas.
- Chain depth limit + circuit breaker en N llamadas/min.
- Evidencia: `.apex/security/L4-planning.md` — risk scores por tool,
  límites configurados.

### L5 — Execution (Fase 10)

Protege: ejecución de código, llamadas a servicios externos.

- **OWASP ASI05 (Code Execution) · ASI02 (Tool Misuse) · ASI03 (Identity Abuse)**
- DNS rebinding guards en todas las requests outbound.
- Rate limiting (por IP, por user, por tool).
- Circuit breakers con half-open state tras cooldown.
- Resource budgets: CPU/memoria/disk caps por invocación.
- Ejecución aislada (sandbox) para código generado/ejecutado.
- Evidencia: `.apex/security/L5-execution.md` — configuración de
  rate limits, CBs, resource caps.

### L6 — Output (Fase 10)

Protege: respuestas al usuario, prevención de exfiltración.

- **OWASP ASI09 (Human Trust Risk)**
- Credential redaction en todas las outputs.
- PII scanner (emails, DNI, teléfonos, IBAN).
- Harmful content blocking (si el dominio lo requiere).
- Exfiltration detection: patrones de datos sensibles saliendo en
  respuestas "inocentes".
- Audit logger: log de outputs críticos para revisión post-hoc.
- Evidencia: `.apex/security/L6-output.md` — 5 scanners activos +
  ejemplos de logs.

### L7 — Inter-Agent (Fases 6, 7 — si hay SMA)

Protege: comunicación entre agentes, cadenas de delegación.

- **OWASP ASI07 (Inter-Agent Communication)**
- Mutual auth con HMAC firmado en cada mensaje.
- Trust scoring con time-decay: agentes conocidos suben score;
  inactividad lo baja.
- Delegation depth control: N niveles max (default 3).
- Evidencia: `.apex/security/L7-inter-agent.md` — esquema de auth,
  trust matrix si aplica.

### L8 — Identity (Fases 10, 11)

Protege: identidades de agentes, credenciales, permisos.

- **OWASP ASI03 (Identity Abuse) · ASI10 (Rogue Agents)**
- Cada agente tiene identity verificable (public key / DID).
- JIT permissions: solo se dan permisos durante la acción, se
  revocan al terminar.
- Credential rotation (≤90 días) con alerta si expira en <7 días.
- Evidencia: `.apex/security/L8-identity.md` — agentes registrados
  + política de rotación.

### Mapeo OWASP ASI Top-10 → Capas AgentArmor

| ASI | Riesgo | Capas que cubren |
|-----|--------|------------------|
| ASI01 | Goal Hijacking | L1 · L3 |
| ASI02 | Tool Misuse | L4 · L5 |
| ASI03 | Identity Abuse | L8 · L5 |
| ASI04 | Supply Chain | L1 |
| ASI05 | Code Execution | L5 · L4 |
| ASI06 | Memory Poisoning | L2 · L3 |
| ASI07 | Inter-Agent | L7 |
| ASI08 | Cascading Failures | L4 · L5 |
| ASI09 | Human Trust Risk | L6 |
| ASI10 | Rogue Agents | L8 · L7 |

## Sub-fase 10.5 — Security Gate

Antes de permitir fase 11 (Deploy), ejecutar:

```
apex_security_gate()
```

El gate:

1. Lee `.apex/security/L1-ingestion.md` … `L8-identity.md`.
2. Parsea frontmatter `status`.
3. Si alguno != `passed` → exit 1, bloquea deploy.
4. Genera `.apex/security/audit-report-YYYY-MM-DD.md` con el estado
   de cada capa y recomendaciones de remediación.

Usar `apex_scaffold_devops` + el skill `devops` en paralelo: el CI/CD
debe depender del security gate antes de permitir el deploy-prod job.

## Protocolo de verificación fase 10.5

- [ ] `.apex/security/` contiene los 8 archivos L1–L8.md
- [ ] Cada uno tiene frontmatter `status: passed` con evidencia
- [ ] `apex_security_gate` exit 0
- [ ] Reporte audit-report-YYYY-MM-DD.md generado
- [ ] Usuario aprobó el reporte antes de disparar deploy
