#!/usr/bin/env bash
# Etapa 9 — placar ENEM (0–1000 por categoria + geral), relatorio.md e placar.json. Pode rodar quantas vezes quiser.
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "pontuação $1"
prova pontuar "$1"
