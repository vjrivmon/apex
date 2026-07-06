#!/usr/bin/env bash
# verify-apex-binding.sh — Comprueba que un proyecto guiado tiene TODO el
# binding de APEX aplicado. Corre esto DENTRO del proyecto nuevo tras el
# primer apex_init_project. Verifica artefactos físicos, no promesas.
#
# Uso:  bash /home/vicente/RoadToDevOps/apex/scripts/verify-apex-binding.sh
#       (desde la raíz del proyecto guiado)

set -uo pipefail
ROOT="$(pwd)"
APEX_ROOT="$(readlink -f ~/.claude/commands/apex.md 2>/dev/null | xargs -r dirname | xargs -r dirname)"
pass=0; fail=0
ok()  { echo "  OK   $1"; pass=$((pass+1)); }
no()  { echo "  FALLA $1"; fail=$((fail+1)); }

echo "== APEX binding check en: $ROOT =="

# 1. /apex global es symlink al repo (no copia stale)
if [ -L ~/.claude/commands/apex.md ] && [ "$(readlink -f ~/.claude/commands/apex.md)" = "$APEX_ROOT/commands/apex.md" ]; then
  ok "/apex global es symlink al router del repo"
else
  no "/apex global NO es symlink al repo (corre scripts/install.sh)"
fi

# 2. .apex/context.db existe
[ -f "$ROOT/.apex/context.db" ] && ok ".apex/context.db creada" || no ".apex/context.db NO existe (corre apex_init_project)"

# 3. CLAUDE.md binding presente
if [ -f "$ROOT/CLAUDE.md" ] && grep -q "APEX:BEGIN" "$ROOT/CLAUDE.md"; then
  ok "CLAUDE.md tiene bloque APEX (reglas en contexto always-on)"
else
  no "CLAUDE.md sin bloque APEX (las 20 reglas NO entran en contexto)"
fi

# 4. settings.json con los gates
S="$ROOT/.claude/settings.json"
if [ -f "$S" ]; then
  grep -q "phase-gate.py" "$S" && ok "hook phase-gate.py registrado" || no "phase-gate.py NO registrado"
  grep -q "code-before-phase5-gate.py" "$S" && ok "hook code-before-phase5-gate.py (write-gate) registrado" || no "write-gate NO registrado"
else
  no ".claude/settings.json NO existe"
fi

# 5. wiki scaffold (APEX lo crea bajo .apex/wiki/)
if [ -d "$ROOT/.apex/wiki" ] || [ -d "$ROOT/wiki" ]; then
  ok "wiki scaffold presente"
else
  no "wiki NO existe (ni .apex/wiki/ ni wiki/)"
fi

echo ""
echo "== Resultado: $pass OK / $fail FALLAS =="
[ "$fail" -eq 0 ] && echo "Binding COMPLETO." || echo "Binding INCOMPLETO — revisa las FALLAS."
exit "$fail"
