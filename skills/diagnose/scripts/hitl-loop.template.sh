#!/usr/bin/env bash
# Bucle de reproducción human-in-the-loop.
# Copia este archivo, edita los pasos abajo y córrelo.
# El agente corre el script; el usuario sigue prompts en su terminal.
#
# Uso:
#   bash hitl-loop.template.sh
#
# Dos helpers:
#   step "<instruccion>"          → muestra instrucción, espera Enter
#   capture VAR "<pregunta>"      → muestra pregunta, lee respuesta a VAR
#
# Al final, los valores capturados se imprimen como KEY=VALUE para que el agente los parsee.

set -euo pipefail

step() {
  printf '\n>>> %s\n' "$1"
  read -r -p "    [Enter cuando termines] " _
}

capture() {
  local var="$1" question="$2" answer
  printf '\n>>> %s\n' "$question"
  read -r -p "    > " answer
  printf -v "$var" '%s' "$answer"
}

# --- editar abajo -------------------------------------------------------

step "Abre la app en http://localhost:3000 y haz login."

capture ERRORED "Haz click en 'Export'. ¿Lanzó error? (y/n)"

capture ERROR_MSG "Pega el mensaje de error (o 'none'):"

# --- editar arriba ------------------------------------------------------

printf '\n--- Capturado ---\n'
printf 'ERRORED=%s\n' "$ERRORED"
printf 'ERROR_MSG=%s\n' "$ERROR_MSG"
