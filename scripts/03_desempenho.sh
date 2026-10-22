#!/usr/bin/env bash
# Etapa 3 — velocidade: prefill e geração com prompts de ~512, 4k e 16k tokens (2 repetições). ~2–4 min.
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "desempenho $1"
prova desempenho "$1"
