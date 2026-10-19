# CLAUDE.md — APEX

> **El estado de este proyecto vive en [`AGENTS.md`](AGENTS.md).** Este
> fichero es el que carga Claude Code; `AGENTS.md` es el que cargan Codex y
> los demás agentes, y es la fuente única. No dupliques la narrativa aquí:
> lo que se escriba en los dos se acaba contradiciendo, que es exactamente
> lo que pasó entre el 2026-04 y el 2026-09-23 con este mismo fichero.
>
> Hasta el 2026-10-19 este fichero tenía su propia copia de la narrativa y
> las dos se divergieron. La copia de `AGENTS.md` es la que manda; lo que
> faltaba en ella se portó allí.

## Qué es APEX

Sistema de skills + MCP server que guía el ciclo completo de desarrollo de
software. Usa una BD SQLite contextual por proyecto (`.apex/context.db`) +
un segundo cerebro (ingest/lint/synthesis) + un dashboard cross-project
(`apex-hub`, repo aparte en `~/RoadToDevOps/apex-hub/`) para que el agente
nunca pierda el hilo.

**Arquitectura: puro CLI + MCP + skills.** El frontend/backend web legacy
vive en la rama `archive/legacy-web` y NO se carga en el flujo actual.

---

<!-- APEX:STATE:BEGIN -->

## Estado verificado

> Generado por `scripts/refresh_state.py` contando el repo.
> NO editar a mano: se sobreescribe. La narrativa va fuera de este
> bloque. Las filas de hooks globales y de la BD viva dependen de la
> máquina: se reportan, pero `--check` no las cuenta como deriva. La
> sección de contexto es volátil y tampoco fuerza reescritura.

| Métrica | Valor |
|---|---|
| Tests (funciones de test) | 1116 |
| Tests (suite ejecutada) | 876 pasando, 4 omitidos (snapshot 2026-10-19, 762 funciones de test) |
| Tools MCP | 64 |
| Skills (`skills/`) | 25 |
| Hooks en disco | 13 |
| Hooks registrados en el proyecto | 8 |
| Hooks registrados globalmente (`~/.claude/settings.json`) | 5 |
| Tablas en el schema (`lib/context_db.py`) | 28 |
| Tablas en la BD viva (`.apex/context.db`) | 34 |

### Artefactos por sprint

Señal mecánica: si el fichero existe, el trabajo se escribió. No dice
si el sprint está *cerrado* — eso es juicio y vive en la narrativa.

| Sprint | Artefactos | Detalle |
|---|---|---|
| S12 roles | presente | lib/roles.py |
| S13 doctor | presente | lib/apex_doctor.py, lib/wrapup_phrases.py |
| S14 skills Pocock | presente | skills/tdd/SKILL.md, skills/diagnose/SKILL.md |
| S15 advisor + traces | presente | lib/advisor.py, lib/reasoning_traces.py |
| S16 advisor feedback | presente | lib/advisor_outcomes.py, lib/advisor_health.py |
| S17 VirtualFS | presente | lib/vfs.py, lib/vfs_grep.py |
| S18 Granite curator | presente | lib/curator.py |
| S19 Advent integration | ausente | ningún artefacto |
| Biblioteca de libros | presente | lib/book_chunker.py, lib/book_corpus.py |

### Módulos sin importadores

Código escrito que nadie usa. Suele ser trabajo a medias, no
necesariamente muerto: verificar antes de borrar o cablear.

- `lib/fts_query.py`

### Contexto del repo (volátil)

Rama `main` (árbol sucio) · HEAD `b738ea4 feat(regla-18): el retrieval cross-project pasa a ser obligatorio de verdad` · refrescado el 2026-10-19.

<!-- APEX:STATE:END -->

---

## Cómo ejecutar

```bash
# Tests
cd ~/RoadToDevOps/apex
PYTHONPATH=lib .venv/bin/pytest tests/ -v

# Regenerar el bloque de estado de CLAUDE.md y AGENTS.md
.venv/bin/python scripts/refresh_state.py

# Refrescar el recuento de suite (instantánea con fecha; tarda ~20 s)
.venv/bin/python scripts/refresh_state.py --run-tests

# Comprobar si está desfasado sin escribir (útil en hooks/CI)
.venv/bin/python scripts/refresh_state.py --check
```

El bloque de arriba se genera con `scripts/refresh_state.py` contando el
repo. **No se edita a mano.** Si añades tests, regenera el bloque antes de
commitear: el control de deriva (`--check`) lo detecta y falla.

## Hooks

Los hooks de Claude Code viven en `.claude/hooks/` y se registran en
`.claude/settings.json` (proyecto) y `~/.claude/settings.json` (global,
para que APEX actúe en todos los proyectos). Hay un juego equivalente para
Codex en `.codex/hooks/`, con su propio registro `.codex/hooks.json`.

La lista de hooks y su alcance están en `AGENTS.md`, sección "Estado por
área".
