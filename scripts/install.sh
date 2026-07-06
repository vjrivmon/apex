#!/usr/bin/env bash
# install.sh — Enlaza los comandos APEX del repo al directorio global de Claude
# Code, de modo que la fuente de verdad del repo sea SIEMPRE lo que se ejecuta.
#
# Causa raíz que esto cierra (auditoría 2026-07-03, cluster C1): el /apex real
# era una copia física stale en ~/.claude/commands/, divergente del router del
# repo. Cada edición al repo tenía efecto CERO en runs reales.
#
# Idempotente. Falla RUIDOSO si un target del repo no existe o si un symlink
# apunta a otro sitio (deriva detectada). Uso: bash scripts/install.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GLOBAL_CMDS="${HOME}/.claude/commands"

# Comandos del repo que se exponen globalmente (basename -> ruta en el repo).
COMMANDS=(
  "apex.md"
  "apex-reverse.md"
  "apex-goal.md"
)

mkdir -p "${GLOBAL_CMDS}"

link_one() {
  local name="$1"
  local target="${REPO_ROOT}/commands/${name}"
  local link="${GLOBAL_CMDS}/${name}"

  if [[ ! -f "${target}" ]]; then
    echo "ERROR: target no existe: ${target}" >&2
    return 1
  fi

  # Ya es el symlink correcto: nada que hacer.
  if [[ -L "${link}" && "$(readlink "${link}")" == "${target}" ]]; then
    echo "ok    ${name} -> ${target} (ya enlazado)"
    return 0
  fi

  # Existe pero apunta a otro sitio o es un fichero físico (deriva): avisar y recrear.
  if [[ -e "${link}" || -L "${link}" ]]; then
    local was
    if [[ -L "${link}" ]]; then was="symlink -> $(readlink "${link}")"; else was="fichero físico ($(wc -c < "${link}") bytes)"; fi
    echo "DRIFT ${name}: ${was}; se reemplaza por symlink al repo" >&2
    rm -f "${link}"
  fi

  ln -s "${target}" "${link}"
  echo "link  ${name} -> ${target}"
}

rc=0
for cmd in "${COMMANDS[@]}"; do
  link_one "${cmd}" || rc=1
done

if [[ ${rc} -ne 0 ]]; then
  echo "install.sh: FALLÓ con errores arriba" >&2
  exit 1
fi

echo "install.sh: ${#COMMANDS[@]} comando(s) APEX enlazados desde ${REPO_ROOT}"
