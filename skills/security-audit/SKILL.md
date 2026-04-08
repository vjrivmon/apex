# SecurityAudit — Auditoria de seguridad automatizada

## Cuando activar

- Fase 10 (seguridad) del flujo APEX
- Antes de cualquier deploy a produccion
- Cuando se anade un nuevo endpoint o se modifica autenticacion
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
