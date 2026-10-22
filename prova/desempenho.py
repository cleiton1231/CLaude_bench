"""Velocidade: prefill (pp) e geração (tg) em vários tamanhos de prompt, + VRAM."""

from __future__ import annotations

import random
import statistics
import time

from .cliente import Cliente
from . import gpu

PALAVRAS = ("sistema dados rede memória processo arquivo módulo função variável servidor cliente "
            "registro tabela índice consulta resultado valor tempo energia sinal circuito placa").split()


def _texto(rng: random.Random, n_palavras: int) -> str:
    return " ".join(rng.choice(PALAVRAS) for _ in range(n_palavras))


def medir(cli: Cliente, ctx: int, seed: int, gerar: int = 256, repeticoes: int = 2) -> dict:
    rng = random.Random(seed)
    tok_por_palavra = cli.contar_tokens(_texto(rng, 400)) / 400
    maior = min(16384, ctx) - gerar - 768  # cabe no ctx junto com a geração
    tamanhos = sorted({t for t in (512, 4096, maior) if 0 < t <= maior})
    linhas = []
    pico = gpu.vram_usada() or 0
    for alvo in tamanhos:
        amostras = []
        for rep in range(repeticoes):
            texto = _texto(rng, int(alvo / tok_por_palavra))  # texto novo = sem cache de prompt
            msgs = [{"role": "user", "content": f"Texto de teste:\n{texto}\n\nContinue escrevendo."}]
            r = cli.chat(msgs, gerar, 0.0, seed + rep,
                         extra={"ignore_eos": True, "cache_prompt": False}, exato=True)
            pico = max(pico, gpu.vram_usada() or 0)
            if r.erro:
                print(f"  {alvo:>6} tok: ERRO {r.erro[:120]}")
                continue
            amostras.append(r)
            print(f"  prompt {r.tokens_prompt:>6} tok  pp {r.pp_tps or 0:>7.1f} tok/s   "
                  f"tg {r.tg_tps or 0:>5.1f} tok/s ({r.tokens_saida} tok)", flush=True)
        if amostras:
            linhas.append({
                "alvo": alvo,
                "tokens_prompt": int(statistics.median(a.tokens_prompt for a in amostras)),
                "pp_tps": round(statistics.median(a.pp_tps or 0 for a in amostras), 1),
                "tg_tps": round(statistics.median(a.tg_tps or 0 for a in amostras), 1),
                "ttft_s": round(statistics.median((a.tokens_prompt / a.pp_tps) if a.pp_tps else 0
                                                  for a in amostras), 2),
            })
    return {"por_tamanho": linhas, "vram_pico_gib": pico or None,
            "gpu_final": gpu.leitura(), "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}
