#!/usr/bin/env bash
# Etapa 0 — checa ambiente antes de tudo: Python, llama-server, GPU, porta, suítes e testes offline.
# Uso: scripts/00_preflight.sh [config/modelos/<perfil>.toml]
source "$(dirname "$0")/_comum.sh"
falhou=0
ok()   { echo "  [ok]   $*"; }
ruim() { echo "  [FALHA] $*"; falhou=1; }
aviso(){ echo "  [aviso] $*"; }

titulo "preflight"
"$PY" -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null \
  && ok "python $("$PY" -V 2>&1 | cut -d' ' -f2)" || ruim "Python >= 3.11 necessário (tomllib)"

eval "$(prova perfil "${1:-config/modelos/exemplo-qwen3-14b-q4km.toml}")"
if [[ -x "$PROVA_BIN" ]]; then
  ok "llama-server: $PROVA_BIN"
  AJUDA="$("$PROVA_BIN" --help 2>&1 || true)"
  grep -q -- "--jinja" <<<"$AJUDA" || ruim "build sem --jinja (antigo demais para tool calling); atualize o llama.cpp"
  grep -qE -- "-fa, --flash-attn [^ ]*(on|auto)" <<<"$AJUDA" \
    || aviso "seu build pode não aceitar '-fa on' (versões antigas usam só '-fa'); se o 01 falhar, ajuste em prova/cli.py"
else
  ruim "llama-server não encontrado em $PROVA_BIN (ajuste config/hardware.toml)"
fi
if [[ -n "${1:-}" ]]; then
  [[ -f "$PROVA_GGUF" ]] && ok "GGUF: $PROVA_GGUF ($(du -h "$PROVA_GGUF" | cut -f1))" || ruim "GGUF não encontrado: $PROVA_GGUF"
fi

V="$(prova vram)"
[[ -n "$V" ]] && ok "GPU AMD detectada (VRAM em uso agora: ${V} GiB)" || aviso "não li a VRAM via sysfs; métricas de VRAM ficarão vazias"
if [[ -n "$V" ]] && "$PY" -c "import sys; sys.exit(0 if float('$V') > 1.5 else 1)"; then
  aviso "já há ${V} GiB em uso na GPU (navegador/compositor?). Isso reduz o espaço para o modelo."
fi

if curl -sf -m 2 "http://$PROVA_HOST:$PROVA_PORTA/health" >/dev/null 2>&1; then
  aviso "já existe um servidor em $PROVA_HOST:$PROVA_PORTA (o 01 vai derrubá-lo)"
else
  ok "porta $PROVA_PORTA livre"
fi
command -v curl >/dev/null && ok "curl" || ruim "curl ausente"
command -v unshare >/dev/null && "$(command -v unshare)" -rn true 2>/dev/null \
  && ok "sandbox sem rede (unshare -rn) disponível" \
  || aviso "unshare -rn indisponível: o código gerado roda SEM isolamento de rede"

prova validar >/dev/null && ok "suítes válidas" || ruim "suítes inválidas (rode: python3 -m prova validar)"
"$PY" -m unittest -q >/dev/null 2>&1 && ok "testes offline" || ruim "testes offline falharam (rode: python3 -m unittest -v)"

titulo "estimativa de tempo"
prova estimar ${1:+"$1"}
exit $falhou
