#!/usr/bin/env bash
# Ensaio do pipeline inteiro contra um servidor FALSO (sem GPU, sem modelo). Serve para o agente
# confirmar que sabe operar os scripts antes da rodada real. Gera resultados/ensaio/.
source "$(dirname "$0")/_comum.sh"
PORTA=8099
"$PY" -m tests.servidor_falso $PORTA >/dev/null 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT
sleep 1
export PROVA_PORTA=$PORTA
rm -rf resultados/ensaio
prova registrar-carga tests/ensaio.toml --segundos 0
for etapa in sanidade desempenho suites agente contexto consistencia pacote pontuar; do
  titulo "$etapa"
  prova "$etapa" ensaio || true
done
echo
echo "Ensaio concluído. Notas baixas são esperadas (respostas enlatadas). Veja resultados/ensaio/relatorio.md"
