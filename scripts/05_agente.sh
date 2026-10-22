#!/usr/bin/env bash
# Etapa 5 — cenários agênticos multi-turno num projeto virtual (corrigir bug, implementar, investigar,
# resistir a prompt injection). ~4–8 min. Retomável; PROVA_REFAZER=1 refaz.
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "agente $1"
ARGS=()
[[ "${PROVA_REFAZER:-0}" == "1" ]] && ARGS+=(--refazer)
prova agente "$1" "${ARGS[@]}"
