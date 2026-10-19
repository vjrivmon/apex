---
layer: L3
title: Context
status: partial
reviewed_by: "apex self-audit (re-verificado 2026-10-19)"
reviewed_at: "2026-10-19"
asi_coverage:
  - ASI01
  - ASI06
evidence:
  - "System prompts: router en commands/apex.md, 16 ficheros de fase en commands/phases/ (00 a 14 mas 10.5-agentarmor-gate.md) mas commands/phases/README.md, y las reglas en commands/rules/absolute-rules.md. Conteo derivado: `ls commands/phases/*.md | wc -l` = 17 (16 fases + README)."
  - "Reglas absolutas: 20 invariantes numerados en commands/rules/absolute-rules.md:6-55 (el ultimo, el 20, cierra en commands/rules/absolute-rules.md:54-55). Verificable con `grep -cE '^[0-9]+\\. ' commands/rules/absolute-rules.md` = 20."
  - "Prompt versioning: todo commands/ y skills/ vive en git; `git log commands/` da la trazabilidad completa. Las skills son Markdown: skills/flow-guardian/SKILL.md:1."
  - "Session isolation: cada proyecto tiene su .apex/context.db propio y el servidor MCP se niega a servir una BD que no sea del proyecto actual (mcp/apex_server.py:309-354). El unico estado compartido entre proyectos es la memoria global append-only de errores graves (lib/global_memory.py:56-95) y el hub.db cross-project, que el MCP abre en modo solo-lectura (mcp/handlers/_common.py:115)."
  - "Canary tokens: NO implementados. No hay ningun token de canario ni hash de prompt en commands/ ni en skills/; la unica mencion de GoalLock es una recomendacion de la skill de auditoria (skills/security-audit/SKILL.md:275)."
---

# L3 — Context

Protege: system prompt, identity anchoring, contexto del agente. Cubre
ASI01 (Goal Hijacking) y ASI06 (Memory Poisoning).

Estado: **partial**. El aislamiento de sesion y el control de memoria
estan verificados y son solidos, pero el control central de esta capa
—detectar que alguien manipulo el prompt del sistema— no existe (F3-01,
F3-02).

## Checklist

- [ ] **GoalLock / canary tokens**: no implementados. No hay token de
      canario en `commands/` ni en `skills/` (solo la recomendacion de
      skills/security-audit/SKILL.md:275). Mitigacion actual: `commands/`
      versionado en git, con un unico contribuidor. Ver F3-01.
- [ ] **Canary verification runtime**: no implementado. Ver F3-01.
- [x] **Template injection stripping** (parcial): los inputs llegan a la
      DB por SQL parametrizado (lib/context_db.py:439, lib/context_db.py:655)
      y no se inyectan en plantillas Jinja: no hay motor de plantillas en
      el repo. El contenido del wiki se renderiza tal cual en Markdown
      (mcp/handlers/wiki.py:35).
- [x] **Prompt storage auditable**: `commands/` + `skills/*/SKILL.md` todo
      en git, cambios auditables con `git log`. Las 20 reglas absolutas
      viven en commands/rules/absolute-rules.md:6-55.
- [x] **Session isolation**: `context.db` por proyecto, y `_get_db()`
      lanza `NotAnApexProjectError` si el cwd no tiene `.apex/` propio o si
      la ruta resuelve a la BD global (mcp/apex_server.py:339-354).
      Excepcion documentada: la memoria global de errores graves, que es
      append-only y de solo lectura para el resto del sistema
      (lib/global_memory.py:56-95).
- [ ] **Diff monitoring runtime**: no implementado. Ver F3-02.

## Findings abiertos

1. **F3-01 (alta)**: 3 canary tokens distribuidos en `commands/apex.md` +
   `commands/rules/absolute-rules.md`, y verificacion de su presencia en
   cada transicion de fase. Evidencia que lo cerraria: los tokens
   presentes en el fichero, la skill `flow-guardian` (o el hook de fase)
   comprobandolos en cada transicion, y un test que borre un token y veas
   el gate bloquear.
2. **F3-02 (media)**: script `lib/prompt_hash.py` que calcule el hash de
   `commands/` + `skills/` al arrancar el MCP server y avise si difiere del
   baseline esperado (stored en `.apex/security/prompt-baseline.json`).
   Evidencia que lo cerraria: el hash persistido, el comparador al
   arrancar y un test que modifique un prompt y compruebe el aviso.
3. **F3-03 (baja, NUEVO)**: la regla "commit firmado" que la checklist
   daba por mitigacion no esta garantizada: el repo depende del
   `git log`, no de firmas. Evidencia que lo cerraria: verificacion de que
   los commits van firmados, o la nota explicita de que la garantia real
   es el control de acceso al repo.

## Verificacion reproducible (2026-10-19)

```bash
# Ficheros de fase (16 fases + README)
ls commands/phases/*.md | wc -l                              # 17
ls commands/phases/ | grep -v README.md | wc -l             # 16
# Reglas absolutas
grep -cE '^[0-9]+\. ' commands/rules/absolute-rules.md        # 20
# Canaries: no existen
grep -rn "canary" commands/ skills/ | grep -v security-audit  # 0
# Aislamiento: la BD global nunca es un proyecto
sed -n '339,354p' mcp/apex_server.py
```
