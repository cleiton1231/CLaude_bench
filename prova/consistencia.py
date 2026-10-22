"""Estabilidade: repete casos marcados com `consistencia = true` com temperatura > 0 e seeds novas."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .cliente import Cliente
from .executor import ler_jsonl, rodar_caso
from .suites import todas

TEMPERATURA = 0.7
SEEDS_EXTRAS = (101, 202)


def rodar(cli: Cliente, dir_modelo: Path, seed: int, mult_tokens: float = 1.0) -> dict:
    gulosos = {}
    for arq in (dir_modelo / "suites").glob("*.jsonl"):
        gulosos.update({r["id"]: r for r in ler_jsonl(arq)})
    casos = [c for s in todas() for c in s["casos"]
             if c["consistencia"] and c["avaliacao"] == "auto" and c["id"] in gulosos]
    linhas = []
    for c in casos:
        qs = [gulosos[c["id"]]["q_auto"]]
        for extra in SEEDS_EXTRAS:
            reg = rodar_caso(cli, c, seed + extra, TEMPERATURA, mult_tokens)
            qs.append(reg["q_auto"])
        estavel = len({q == 1 for q in qs}) == 1
        linhas.append({"id": c["id"], "dificuldade": c["dificuldade"], "q": qs, "estavel": estavel})
        print(f"  {c['id']:<42} {' '.join('OK' if q == 1 else '--' for q in qs)} "
              f"{'estável' if estavel else 'INSTÁVEL'}", flush=True)
    n = len(linhas) or 1
    res = {
        "temperatura": TEMPERATURA, "casos": linhas,
        "taxa_estavel": round(sum(l["estavel"] for l in linhas) / n, 3),
        "acerto_guloso": round(sum(l["q"][0] == 1 for l in linhas) / n, 3),
        "acerto_amostrado": round(sum(q == 1 for l in linhas for q in l["q"][1:]) / (2 * n), 3),
        "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (dir_modelo / "consistencia.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    return res
