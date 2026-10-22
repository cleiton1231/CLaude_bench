#!/usr/bin/env bash
# Atalho: roda as etapas 01→07, para o servidor e gera o pacote do juiz (08).
# O julgamento (notas_juiz.json) e a etapa 09 continuam com o agente.
# Uso: scripts/rodar_modelo.sh config/modelos/<perfil>.toml
source "$(dirname "$0")/_comum.sh"
PERFIL="${1:?uso: $0 config/modelos/<perfil>.toml}"
eval "$(prova perfil "$PERFIL")"
S="$RAIZ/scripts"
trap '"$S/10_parar_modelo.sh" >/dev/null 2>&1 || true' EXIT
"$S/01_subir_modelo.sh" "$PERFIL"
"$S/02_sanidade.sh" "$PROVA_ID"
"$S/03_desempenho.sh" "$PROVA_ID"
"$S/04_suites.sh" "$PROVA_ID"
"$S/05_agente.sh" "$PROVA_ID"
"$S/06_contexto.sh" "$PROVA_ID"
"$S/07_consistencia.sh" "$PROVA_ID"
"$S/10_parar_modelo.sh"
"$S/08_pacote_juiz.sh" "$PROVA_ID"
"$S/09_pontuar.sh" "$PROVA_ID"
echo "Agora: julgar resultados/$PROVA_ID/pacote_juiz.md seguindo JULGAMENTO.md e rodar 09 de novo."
