#!/usr/bin/env bash
# Etapa 7 — estabilidade: repete ~20 casos marcados com temperatura 0.7 e duas seeds. ~3–5 min.
# Não entra na nota; vai para o relatório como indicador de confiabilidade.
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "consistência $1"
prova consistencia "$1"
