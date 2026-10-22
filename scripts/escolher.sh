#!/usr/bin/env bash
# Escolhe quais testes rodar. Sem argumento: menu interativo. Com argumento: rodada direta.
# Uso: scripts/escolher.sh                 (menu)
#      scripts/escolher.sh rapida          (grava config/selecao.toml com a rodada "rapida")
#      scripts/escolher.sh completa --suites codigo,ferramentas
# Ver a seleção atual: python3 -m prova rodada
source "$(dirname "$0")/_comum.sh"
prova escolher "$@"
