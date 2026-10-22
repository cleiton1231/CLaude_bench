#!/usr/bin/env bash
# Mostra o andamento de um modelo: etapas concluídas, etapa em fundo, últimas linhas do log.
source "$(dirname "$0")/_comum.sh"
ID="${1:?uso: $0 <id>}"
D="resultados/$ID"
[[ -f "$D/meta.json" ]] || { echo "sem resultados para $ID"; exit 1; }
"$PY" - "$D/meta.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
et = m.get("etapas", {})
total = sum(e["minutos"] for e in et.values())
print(f"carregado em {m.get('carregado_em')} · VRAM {m.get('vram_carregado_gib')} GiB")
for k, v in et.items():
    print(f"  ✔ {k:<14} {v['minutos']:>6.1f} min  ({v['fim']})")
print(f"  total medido: {total:.1f} min")
PY
for pidf in "$D"/logs/*.pid; do
  [[ -e "$pidf" ]] || continue
  pid="$(cat "$pidf")"; log="${pidf%.pid}.log"
  if kill -0 "$pid" 2>/dev/null; then
    echo "  ⏳ $(basename "${pidf%.pid}") rodando (pid $pid):"
    tail -n 3 "$log" | sed 's/^/     /'
  else
    echo "  · $(basename "${pidf%.pid}") terminou: $(tail -n 1 "$log")"
  fi
done
