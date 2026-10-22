#!/usr/bin/env bash
# Etapa 1 — derruba qualquer llama-server, sobe o modelo do perfil, mede tempo de carga e VRAM.
# Uso: scripts/01_subir_modelo.sh config/modelos/<perfil>.toml
source "$(dirname "$0")/_comum.sh"
PERFIL="${1:?uso: $0 config/modelos/<perfil>.toml}"
eval "$(prova perfil "$PERFIL")"
DIR="resultados/$PROVA_ID"
if [[ -f "$DIR/meta.json" ]]; then
  echo "AVISO: já existem resultados em $DIR; as etapas vão RETOMAR de onde pararam."
  echo "        Para uma rodada limpa: rm -rf $DIR (ou crie outro perfil)."
fi
mkdir -p "$DIR/logs"

"$RAIZ/scripts/10_parar_modelo.sh" >/dev/null 2>&1 || true
sleep 2
VRAM_BASE="$(prova vram)"

[[ -x "$PROVA_BIN" ]] || { echo "ERRO: llama-server não encontrado: $PROVA_BIN"; exit 1; }
[[ -f "$PROVA_GGUF" ]] || { echo "ERRO: GGUF não encontrado: $PROVA_GGUF"; exit 1; }

titulo "subindo $PROVA_NOME"
echo "flags: ${PROVA_FLAGS[*]}"
INICIO=$(date +%s.%N)
env "${PROVA_AMBIENTE[@]}" setsid "$PROVA_BIN" --model "$PROVA_GGUF" --host "$PROVA_HOST" --port "$PROVA_PORTA" \
  "${PROVA_FLAGS[@]}" </dev/null >"$DIR/logs/llama-server.log" 2>&1 &
PID=$!
echo "$PID" > resultados/.servidor.pid
echo "$PROVA_ID" > resultados/.servidor.id

for _ in $(seq 1 300); do
  if curl -sf -m 2 "http://$PROVA_HOST:$PROVA_PORTA/health" >/dev/null 2>&1; then
    SEG=$(awk "BEGIN{printf \"%.1f\", $(date +%s.%N) - $INICIO}")
    sleep 1
    prova registrar-carga "$PERFIL" --segundos "$SEG" --vram-base "${VRAM_BASE:-}"
    if grep -qiE "failed to allocate|out of memory|ErrorOutOfDeviceMemory" "$DIR/logs/llama-server.log"; then
      echo "AVISO: o log do servidor menciona falha de alocação. Confira $DIR/logs/llama-server.log"
    fi
    # coleta de sensores em segundo plano até o 10_parar_modelo
    nohup "$RAIZ/scripts/sensores_gpu.sh" "$DIR/sensores.csv" 5 >/dev/null 2>&1 &
    echo $! > resultados/.sensores.pid
    echo "pronto em ${SEG}s (pid $PID). Log: $DIR/logs/llama-server.log"
    exit 0
  fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "ERRO: llama-server morreu durante a carga. Fim do log:"
    tail -n 40 "$DIR/logs/llama-server.log"
    exit 1
  fi
  sleep 1
done
echo "ERRO: timeout de 300 s esperando o servidor."
tail -n 40 "$DIR/logs/llama-server.log"
exit 1
