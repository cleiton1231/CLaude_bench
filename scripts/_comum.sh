#!/usr/bin/env bash
# Funções compartilhadas pelos scripts de etapa. Não execute diretamente.
set -euo pipefail
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
PY="${PY:-python3}"
RES="${PROVA_RESULTADOS:-$RAIZ/resultados}"   # onde cada rodada grava seus arquivos
mkdir -p "$RES"
prova() { "$PY" -m prova "$@"; }

exigir_id() {
  if [[ -z "${1:-}" ]]; then
    echo "uso: $(basename "$0") <id-do-modelo>   (id = nome do perfil sem .toml)" >&2
    exit 2
  fi
  if [[ ! -f "$RES/$1/meta.json" ]]; then
    echo "ERRO: $RES/$1/meta.json não existe. Rode antes: scripts/01_subir_modelo.sh config/modelos/$1.toml" >&2
    exit 2
  fi
}

titulo() { printf '\n========== %s ==========\n' "$*"; }
