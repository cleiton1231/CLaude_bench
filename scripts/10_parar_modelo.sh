#!/usr/bin/env bash
# Etapa 10 — derruba o llama-server que o 01 subiu e o coletor de sensores, liberando a VRAM.
# Só mexe no servidor DESTA prova (pelo PID gravado ou pela porta configurada); um llama-server seu
# rodando em outra porta não é afetado.
source "$(dirname "$0")/_comum.sh"
eval "$(prova servidor)"
parar_pid() {
  local pid="$1"
  kill "$pid" 2>/dev/null || return 0
  for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || return 0; sleep 1; done
  kill -9 "$pid" 2>/dev/null || true
}
for pf in "$RES/.sensores.pid" "$RES/.servidor.pid"; do
  [[ -f "$pf" ]] && parar_pid "$(cat "$pf")"
  rm -f "$pf"
done
for _ in $(seq 1 15); do
  if ! curl -sf -m 1 "http://$PROVA_HOST:$PROVA_PORTA/health" >/dev/null 2>&1; then
    echo "servidor parado; VRAM em uso: $(prova vram) GiB"
    rm -f "$RES/.servidor.id"
    exit 0
  fi
  # sobrou um servidor nesta porta sem pidfile (ex.: 01 interrompido): mata só ele
  pkill -f -- "llama-server.*--port $PROVA_PORTA( |$)" 2>/dev/null || true
  sleep 1
done
echo "ERRO: porta $PROVA_PORTA continua ocupada por um processo que não é desta prova"
exit 1
