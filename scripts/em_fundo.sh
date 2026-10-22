#!/usr/bin/env bash
# Roda uma etapa longa em segundo plano (imune a timeout da ferramenta do agente).
# Uso: scripts/em_fundo.sh 04_suites.sh <id> [args...]   → acompanhe com scripts/status.sh <id>
source "$(dirname "$0")/_comum.sh"
ETAPA="${1:?uso: $0 <script> <id> [args]}"; shift
ID="${1:?id do modelo}"
mkdir -p "resultados/$ID/logs"
LOG="resultados/$ID/logs/${ETAPA%.sh}.log"
nohup "$RAIZ/scripts/$ETAPA" "$@" >"$LOG" 2>&1 &
echo $! > "resultados/$ID/logs/${ETAPA%.sh}.pid"
echo "rodando em segundo plano: pid $! · log $LOG"
