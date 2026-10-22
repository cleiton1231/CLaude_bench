#!/usr/bin/env bash
# Etapa 8 — gera resultados/<id>/pacote_juiz.md e notas_juiz.modelo.json. Não precisa do servidor.
# Depois: o agente-juiz lê JULGAMENTO.md, julga e grava resultados/<id>/notas_juiz.json.
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "pacote do juiz $1"
prova pacote "$1"
