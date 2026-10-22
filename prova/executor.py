"""Roda casos de suíte contra o servidor e grava JSONL retomável."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from .cliente import Cliente, Resposta
from .ferramentas import schemas
from .verificadores import avaliar

MAX_RODADAS_FERRAMENTA = 5


def hash_caso(caso: dict) -> str:
    chave = json.dumps({k: caso.get(k) for k in ("prompt", "sistema", "checks", "turnos_seguintes",
                                                  "ferramentas", "resultados", "gabarito")},
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(chave.encode()).hexdigest()[:10]


def _resultado_simulado(caso: dict, chamada: dict) -> str:
    for r in caso.get("resultados", []):
        if r["nome"] == chamada["nome"] and re.search(r.get("quando", ""), chamada["args_brutos"], re.I):
            return r["resultado"]
    return json.dumps({"erro": "serviço indisponível no ambiente de teste"}, ensure_ascii=False)


def _somar(total: Resposta, r: Resposta) -> None:
    total.tokens_prompt += r.tokens_prompt
    total.tokens_saida += r.tokens_saida
    total.segundos += r.segundos
    total.chamadas.extend(r.chamadas)
    total.raciocinio += r.raciocinio
    total.texto, total.fim, total.erro = r.texto, r.fim, r.erro or total.erro
    total.pp_tps = r.pp_tps or total.pp_tps
    total.tg_tps = r.tg_tps or total.tg_tps


def _msg_assistente(r: Resposta) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": r.texto}
    if r.chamadas:
        msg["tool_calls"] = [{"id": c["id"], "type": "function",
                              "function": {"name": c["nome"], "arguments": c["args_brutos"] or "{}"}}
                             for c in r.chamadas]
    return msg


def rodar_caso(cli: Cliente, caso: dict, seed: int, temperatura: float = 0.0,
               mult_tokens: float = 1.0) -> dict[str, Any]:
    msgs: list[dict] = []
    if caso.get("sistema"):
        msgs.append({"role": "system", "content": caso["sistema"]})
    msgs.append({"role": "user", "content": caso["prompt"]})
    tools = schemas(caso["ferramentas"]) if caso.get("ferramentas") else None
    max_tok = int(caso["max_tokens"] * mult_tokens)

    total = Resposta()
    pendentes = list(caso.get("turnos_seguintes", []))
    for _ in range(MAX_RODADAS_FERRAMENTA + len(pendentes) + 1):
        r = cli.chat(msgs, max_tok, temperatura, seed, tools)
        _somar(total, r)
        if r.erro:
            break
        msgs.append(_msg_assistente(r))
        if r.chamadas and tools:
            for c in r.chamadas:
                msgs.append({"role": "tool", "tool_call_id": c["id"],
                             "content": _resultado_simulado(caso, c)})
            continue
        if pendentes:
            msgs.append({"role": "user", "content": pendentes.pop(0)})
            continue
        break

    checks = avaliar(total, caso)
    peso = sum(c["peso"] for c in checks) or 1
    q_auto = sum(c["peso"] for c in checks if c["ok"]) / peso if checks else None
    return {
        "id": caso["id"], "suite": caso["suite"], "categoria": caso["categoria"],
        "dificuldade": caso["dificuldade"], "critico": caso["critico"],
        "avaliacao": caso["avaliacao"], "hash": hash_caso(caso),
        "seed": seed, "temperatura": temperatura,
        "resposta": total.resumo(), "checks": checks,
        "q_auto": None if caso["avaliacao"] == "juiz" else q_auto,
        "sinais_ok": q_auto if caso["avaliacao"] == "juiz" else None,
        "transcricao": msgs, "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def ler_jsonl(arq: Path) -> list[dict]:
    if not arq.exists():
        return []
    return [json.loads(ln) for ln in arq.read_text(encoding="utf-8").splitlines() if ln.strip()]


def rodar_suite(cli: Cliente, suite: dict, saida: Path, seed: int, mult_tokens: float = 1.0,
                refazer: bool = False, so_ids: set[str] | None = None) -> list[dict]:
    saida.parent.mkdir(parents=True, exist_ok=True)
    feitos = {} if refazer else {r["id"]: r for r in ler_jsonl(saida)}
    casos = [c for c in suite["casos"] if not so_ids or c["id"] in so_ids]
    # resultado antigo só vale se o caso não mudou desde então
    validos = {cid: r for cid, r in feitos.items()
               if any(c["id"] == cid and hash_caso(c) == r.get("hash") for c in casos)}
    if refazer or len(validos) != len(feitos):
        saida.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in validos.values()),
                         encoding="utf-8")
    t0 = time.monotonic()
    novos = 0
    for i, caso in enumerate(casos, 1):
        if caso["id"] in validos:
            continue
        reg = rodar_caso(cli, caso, seed, 0.0, mult_tokens)
        novos += 1
        with saida.open("a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
        validos[caso["id"]] = reg
        r = reg["resposta"]
        marca = ("?" if reg["avaliacao"] == "juiz" else
                 "OK" if reg["q_auto"] == 1 else "parcial" if reg["q_auto"] else "ERRO")
        decorrido = time.monotonic() - t0
        restante = (len(casos) - i) * decorrido / max(novos, 1)
        tg = f"{r['tg_tps']:.1f}" if r["tg_tps"] else "-"
        print(f"  [{i:>3}/{len(casos)}] {caso['id']:<42} {marca:<7} {r['tokens_saida']:>5} tok "
              f"{r['segundos']:>5.1f}s {tg:>5} tok/s  ~{restante / 60:.1f} min restantes", flush=True)
    return [validos[c["id"]] for c in casos if c["id"] in validos]
