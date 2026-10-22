#!/usr/bin/env bash
# Piloto automático: executa sozinho todos os passos mecânicos (subir modelo, sanidade, etapas, parar,
# pacote, placar, comparativo) de todos os modelos da série, e para quando precisa do agente ou do humano.
#
# Uso: scripts/piloto.sh            (primeiro plano)
#      scripts/piloto.sh --fundo    (segundo plano; acompanhe com scripts/proximo.sh ou o log)
#
# Saída: 0 série concluída · 10 sua vez (julgar/parecer/corrigir) · 20 avisar o humano · 1 comando falhou 2x
source "$(dirname "$0")/_comum.sh"
if [[ "${1:-}" == "--fundo" ]]; then
  shift
  nohup "$PY" -m prova piloto "$@" >"$RES/piloto.log" 2>&1 &
  echo $! >"$RES/.piloto.pid"  # já, antes do python gravar: evita outro piloto/etapa em paralelo
  echo "piloto em segundo plano: pid $! · log $RES/piloto.log"
  echo "acompanhe: scripts/proximo.sh  (mostra AGUARDAR enquanto ele roda)  ou  tail -f $RES/piloto.log"
  exit 0
fi
prova piloto "$@"
