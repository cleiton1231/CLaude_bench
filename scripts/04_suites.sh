#!/usr/bin/env bash
# Etapa 4 — suítes de qualidade (código, raciocínio, instruções, ceticismo, ferramentas, redação). ~18–25 min.
# Retomável: casos já respondidos são pulados. Para refazer tudo: PROVA_REFAZER=1.
# Uso: scripts/04_suites.sh <id> [suite1,suite2]
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "suítes $1 ${2:-(todas)}"
ARGS=()
[[ -n "${2:-}" ]] && ARGS+=(--so "$2")
[[ "${PROVA_REFAZER:-0}" == "1" ]] && ARGS+=(--refazer)
prova suites "$1" "${ARGS[@]}"
