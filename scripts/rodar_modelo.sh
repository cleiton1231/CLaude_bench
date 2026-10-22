#!/usr/bin/env bash
# Atalho: roda todas as etapas da seleção atual para um modelo, para o servidor e gera o pacote do juiz.
# Etapas desligadas na rodada (config/selecao.toml) são puladas automaticamente.
# O julgamento (notas_juiz.json) e o parecer continuam com o agente.
# Uso: scripts/rodar_modelo.sh config/modelos/<perfil>.toml
source "$(dirname "$0")/_comum.sh"
PERFIL="${1:?uso: $0 config/modelos/<perfil>.toml}"
eval "$(prova perfil "$PERFIL")"
S="$RAIZ/scripts"
titulo "seleção"
prova rodada | head -12
prova estimar "$PERFIL" | tail -2
trap '"$S/10_parar_modelo.sh" >/dev/null 2>&1 || true' EXIT
"$S/01_subir_modelo.sh" "$PERFIL"
"$S/02_sanidade.sh" "$PROVA_ID"
for etapa in 03_desempenho 04_suites 05_agente 06_contexto 07_consistencia 11_criticos; do
  "$S/$etapa.sh" "$PROVA_ID"
done
"$S/10_parar_modelo.sh"
"$S/08_pacote_juiz.sh" "$PROVA_ID"
"$S/09_pontuar.sh" "$PROVA_ID"
echo "Agora: julgar $RES/$PROVA_ID/pacote_juiz.md seguindo JULGAMENTO.md e rodar 09 de novo."
