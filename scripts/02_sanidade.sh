#!/usr/bin/env bash
# Etapa 2 — smoke: chat responde, raciocínio desligado de fato, tool calling funciona, /tokenize ok.
# Se falhar, NÃO prossiga: corrija o perfil (template, --jinja, ctx) e volte ao 01.
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "sanidade $1"
prova sanidade "$1"
