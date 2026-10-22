#!/usr/bin/env bash
# Etapa 11 — repete os casos CRÍTICOS (rm -rf, injeções, segredo, bajulação) com várias seeds e
# temperatura 0.7. Mostra "seguro k/N" por caso. Não entra na nota. ~5–10 min.
# Quantidade: repeticoes_criticos / repeticoes_criticos_agente na rodada (config/rodadas/).
source "$(dirname "$0")/_comum.sh"
exigir_id "${1:-}"
titulo "críticos repetidos $1"
prova criticos "$1"
