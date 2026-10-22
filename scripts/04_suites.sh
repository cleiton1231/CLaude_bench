#!/usr/bin/env bash
# Etapa 4 — suítes de qualidade da seleção (config/selecao.toml; padrão: todas). ~15–20 min na completa.
# Retomável: casos já respondidos são pulados. Para refazer tudo: PROVA_REFAZER=1.
# Uso: scripts/04_suites.sh <id> [suite1,suite2]   (o 2º argumento sobrescreve as suítes da seleção)
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "suítes $1 ${2:-(todas)}"
ARGS=()
[[ -n "${2:-}" ]] && ARGS+=(--so "$2")
[[ "${PROVA_REFAZER:-0}" == "1" ]] && ARGS+=(--refazer)
prova suites "$1" "${ARGS[@]}"
