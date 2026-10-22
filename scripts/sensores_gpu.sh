#!/usr/bin/env bash
# Amostra VRAM/ocupação/temperatura/potência da GPU (sysfs amdgpu) num CSV até ser morto.
# Uso: scripts/sensores_gpu.sh <saida.csv> [intervalo_s]
source "$(dirname "$0")/_comum.sh"
OUT="${1:?arquivo csv}"; INT="${2:-5}"
echo "ts,dados_json" > "$OUT"
while :; do
  echo "$(date +%s),$("$PY" -c 'import json; from prova import gpu; print(json.dumps(gpu.leitura()))' | sed 's/,/;/g')" >> "$OUT"
  sleep "$INT"
done
