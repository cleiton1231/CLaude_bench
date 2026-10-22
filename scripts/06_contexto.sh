#!/usr/bin/env bash
# Etapa 6 — contexto longo com dados sintéticos: agulha em 3 posições por tamanho (4k/8k/16k/32k,
# limitado ao ctx do perfil), multi-salto com informação atualizada e contagem. ~3–6 min (prefill).
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "contexto $1"
prova contexto "$1"
