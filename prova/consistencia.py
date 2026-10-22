"""Estabilidade: repete casos marcados com `consistencia = true` com temperatura > 0 e seeds novas."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .cliente import Cliente
from .executor import ler_jsonl, rodar_caso, teve_erro_infra
from .suites import todas

TEMPERATURA = 0.7
SEEDS_EXTRAS = (101, 202)


def rodar(cli: Cliente, dir_modelo: Path, seed: int, mult_tokens: float = 1.0,
          sel: dict | None = None) -> dict:
    from .selecao import filtrar
    gulosos = {}
    for arq in (dir_modelo / "suites").glob("*.jsonl"):
        gulosos.update({r["id"]: r for r in ler_jsonl(arq) if not teve_erro_infra(r)})
    casos = [c for s in todas(sel["suites"] if sel else None)
             for c in (filtrar(s["casos"], sel) if sel else s["casos"])
             if c["consistencia"] and c["avaliacao"] == "auto" and c["id"] in gulosos]
    linhas = []
    for c in casos:
        qs = [gulosos[c["id"]]["q_auto"]]
        for extra in SEEDS_EXTRAS:
            reg = rodar_caso(cli, c, seed + extra, TEMPERATURA, mult_tokens)
            if reg["erro_infra"]:
                continue
            qs.append(reg["q_auto"])
        estavel = len({q == 1 for q in qs}) == 1
        linhas.append({"id": c["id"], "dificuldade": c["dificuldade"], "q": qs, "estavel": estavel})
        print(f"  {c['id']:<42} {' '.join('OK' if q == 1 else '--' for q in qs)} "
              f"{'estável' if estavel else 'INSTÁVEL'}", flush=True)
    n = len(linhas) or 1
    amostras = [q for x in linhas for q in x["q"][1:]]  # sem as repetições que deram erro de servidor
    res = {
        "temperatura": TEMPERATURA, "casos": linhas,
        "taxa_estavel": round(sum(x["estavel"] for x in linhas) / n, 3),
        "acerto_guloso": round(sum(x["q"][0] == 1 for x in linhas) / n, 3),
        "acerto_amostrado": round(sum(q == 1 for q in amostras) / (len(amostras) or 1), 3),
        "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (dir_modelo / "consistencia.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    return res
