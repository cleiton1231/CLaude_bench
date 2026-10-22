#!/usr/bin/env bash
# Etapa 10 — derruba o llama-server e o coletor de sensores, libera a VRAM.
source "$(dirname "$0")/_comum.sh"
for pf in resultados/.sensores.pid resultados/.servidor.pid; do
  if [[ -f "$pf" ]]; then
    pid="$(cat "$pf")"
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$pf"
  fi
done
pkill -f 'llama-server' 2>/dev/null || true
eval "$(prova perfil config/modelos/exemplo-qwen3-14b-q4km.toml)"
for _ in $(seq 1 20); do
  if ! curl -sf -m 1 "http://$PROVA_HOST:$PROVA_PORTA/health" >/dev/null 2>&1; then
    echo "servidor parado; VRAM em uso: $(prova vram) GiB"
    rm -f resultados/.servidor.id
    exit 0
  fi
  pkill -9 -f 'llama-server' 2>/dev/null || true
  sleep 1
done
echo "ERRO: porta $PROVA_PORTA continua ocupada"
exit 1
