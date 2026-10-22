#!/usr/bin/env bash
# Diz exatamente o próximo passo da série, olhando o estado real (config, perfis, resultados, servidor,
# notas do juiz, parecer). Comece SEMPRE por aqui. `--json` para saída de máquina.
source "$(dirname "$0")/_comum.sh"
prova proximo "$@"
