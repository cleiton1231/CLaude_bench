#!/usr/bin/env bash
# Instalação guiada: confere dependências, acha o llama-server, grava config/local.toml,
# cria perfis para seus GGUFs, escolhe a rodada e valida tudo com testes offline + ensaio.
#
# Uso: scripts/instalar.sh                       (interativo)
#      scripts/instalar.sh --auto [--bin CAMINHO] [--modelos PASTA] [--rodada NOME]
#      (--auto não pergunta nada: usa o que detectar; bom para o agente)
#      --sem-validar pula os testes offline e o ensaio do final
source "$(dirname "$0")/_comum.sh"

AUTO=0; BIN=""; MODELOS=""; RODADA=""; VALIDAR=1
LOCAL="${PROVA_CONFIG_LOCAL:-config/local.toml}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto) AUTO=1 ;;
    --bin) BIN="$2"; shift ;;
    --modelos) MODELOS="$2"; shift ;;
    --rodada) RODADA="$2"; shift ;;
    --sem-validar) VALIDAR=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1"; exit 2 ;;
  esac
  shift
done

perguntar() {  # perguntar "texto" "padrão" -> echo resposta
  local resp=""
  if [[ $AUTO -eq 1 ]]; then echo "$2"; return; fi
  read -r -p "$1 [${2:-vazio}]: " resp </dev/tty || true
  echo "${resp:-$2}"
}

DISTRO="$(. /etc/os-release 2>/dev/null && echo "${ID_LIKE:-} ${ID:-}")"
cmd_instalar() {  # sugere o comando de instalação do pacote $1 para a distro
  case "$DISTRO" in
    *fedora*|*rhel*) echo "sudo dnf install $1" ;;
    *arch*) echo "sudo pacman -S $1" ;;
    *debian*|*ubuntu*) echo "sudo apt install $1" ;;
    *suse*) echo "sudo zypper install $1" ;;
    *) echo "instale o pacote '$1' pelo gerenciador da sua distro" ;;
  esac
}

titulo "1/6 dependências"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "  [FALHA] Python >= 3.11 necessário. $(cmd_instalar python3)"; exit 1
fi
echo "  [ok] $("$PY" -V)"
command -v curl >/dev/null && echo "  [ok] curl" || { echo "  [FALHA] curl ausente: $(cmd_instalar curl)"; exit 1; }
if command -v bwrap >/dev/null; then
  echo "  [ok] bubblewrap (sandbox forte)"
else
  echo "  [aviso] bubblewrap ausente: o código gerado pelo modelo rodará com isolamento fraco."
  echo "          Recomendado: $(cmd_instalar bubblewrap)"
fi

titulo "2/6 llama-server"
if [[ -z "$BIN" ]]; then
  for c in "$(command -v llama-server 2>/dev/null || true)" \
           "$HOME"/llama.cpp/build*/bin/llama-server "$HOME"/Projetos/llama.cpp/build*/bin/llama-server \
           "$HOME"/projetos/llama.cpp/build*/bin/llama-server "$HOME"/src/llama.cpp/build*/bin/llama-server \
           /usr/local/bin/llama-server /opt/llama.cpp/build/bin/llama-server; do
    [[ -n "$c" && -x "$c" ]] && { BIN="$c"; break; }
  done
fi
BIN="$(perguntar "Caminho do llama-server" "$BIN")"
BIN="${BIN/#\~/$HOME}"
if [[ -x "$BIN" ]]; then
  echo "  [ok] $BIN"
  "$BIN" --help 2>&1 | grep -q -- "--jinja" || echo "  [aviso] build sem --jinja: atualize o llama.cpp (tool calling não vai funcionar)"
else
  echo "  [aviso] llama-server não encontrado em '$BIN'. Compile o llama.cpp com Vulkan:"
  echo "          cmake -B build -DGGML_VULKAN=ON && cmake --build build -j  (depois rode este script de novo)"
fi
PORTA="$(perguntar "Porta do servidor" "8080")"

titulo "3/6 $LOCAL"
if [[ -f "$LOCAL" && $AUTO -eq 0 ]]; then
  [[ "$(perguntar "$LOCAL já existe. Sobrescrever? (s/n)" "n")" == s* ]] || SALTAR_LOCAL=1
fi
if [[ -z "${SALTAR_LOCAL:-}" ]]; then
  cat > "$LOCAL" <<TOML
# Configuração desta máquina (fora do git). Sobrescreve config/hardware.toml.
[servidor]
binario = "$BIN"
porta = $PORTA

[sandbox]
modo = "auto"
TOML
  echo "  gravado $LOCAL"
fi
"$PY" -m prova sandbox | sed 's/^/  /'

titulo "4/6 perfis de modelo"
MODELOS="$(perguntar "Pasta com seus .gguf (enter para pular)" "$MODELOS")"
MODELOS="${MODELOS/#\~/$HOME}"
if [[ -n "$MODELOS" && -d "$MODELOS" ]]; then
  mapfile -t GGUFS < <(find "$MODELOS" -maxdepth 3 -iname '*.gguf' ! -iname '*mmproj*' \
                       ! -iname '*-0000[2-9]-of-*' | sort)
  if [[ ${#GGUFS[@]} -eq 0 ]]; then
    echo "  nenhum .gguf em $MODELOS"
  else
    prova novo-perfil "${GGUFS[@]}" | sed 's/^/  /'
  fi
else
  echo "  pulado. Depois: python3 -m prova novo-perfil /caminho/modelo.gguf"
fi

titulo "5/6 o que rodar"
if [[ -n "$RODADA" ]]; then
  prova escolher "$RODADA" | sed 's/^/  /'
elif [[ $AUTO -eq 1 ]]; then
  [[ -f config/selecao.toml ]] || prova escolher completa | sed 's/^/  /'
else
  prova escolher
fi

if [[ $VALIDAR -eq 0 ]]; then echo; echo "Instalação concluída (validação pulada)."; exit 0; fi
titulo "6/6 validação"
"$PY" -m unittest -q >/dev/null 2>&1 && echo "  [ok] testes offline" || { echo "  [FALHA] testes offline: rode $PY -m unittest -v"; exit 1; }
"$RAIZ/scripts/ensaio_sem_gpu.sh" >/dev/null 2>&1 && echo "  [ok] ensaio com servidor falso" || echo "  [FALHA] ensaio: rode scripts/ensaio_sem_gpu.sh"
rm -rf "$RES/ensaio"
echo
echo "Pronto. Próximo passo: scripts/00_preflight.sh config/modelos/<perfil>.toml"
