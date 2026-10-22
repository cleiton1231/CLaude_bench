"""Piloto automático: executa os passos mecânicos da série até precisar de inteligência ou de um humano.

Códigos de saída (para o agente decidir sem ler a saída):
  0   série concluída (ação `fim`)
  10  sua vez: julgar, escrever parecer ou corrigir um arquivo seu
  20  parar e avisar o humano (bloqueado/configurar)
  1   um comando falhou duas vezes seguidas
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from . import config, plano

SAIDA = {"fim": 0, "julgar": 10, "parecer": 10, "corrigir": 10, "bloqueado": 20, "configurar": 20, "aguardar": 20}


def rodar(max_passos: int = 200) -> int:
    pidf = config.RESULTADOS / ".piloto.pid"
    config.RESULTADOS.mkdir(parents=True, exist_ok=True)
    pidf.write_text(str(os.getpid()))
    ultimo, falhas = None, 0
    t0 = time.monotonic()
    try:
        for passo in range(1, max_passos + 1):
            a = plano.proximo()
            if a["acao"] != "rodar":
                print(f"\n[piloto] parou após {passo - 1} passo(s), {(time.monotonic() - t0) / 60:.1f} min",
                      flush=True)
                print(plano.texto(a, plano.progresso(), _rodada()), flush=True)
                return SAIDA.get(a["acao"], 20)
            cmd = a["comando"]
            print(f"\n[piloto] passo {passo}: {' '.join(cmd)}\n[piloto] por quê: {a['motivo']}", flush=True)
            rc = subprocess.run(cmd, cwd=config.RAIZ).returncode
            if rc != 0:
                falhas = falhas + 1 if cmd == ultimo else 1
                print(f"[piloto] comando terminou com código {rc} (falha {falhas}/2)", flush=True)
                if falhas >= 2:
                    print(f"[piloto] PARANDO: o mesmo comando falhou duas vezes. {a.get('se_falhar', '')}",
                          flush=True)
                    return 1
            else:
                falhas = 0
            ultimo = cmd
        print(f"[piloto] PARANDO: limite de {max_passos} passos (laço?)", flush=True)
        return 1
    finally:
        if pidf.exists() and pidf.read_text().strip() == str(os.getpid()):
            pidf.unlink()


def _rodada() -> str:
    from . import selecao
    try:
        return selecao.carregar()["nome"]
    except selecao.SelecaoInvalida:
        return "?"


def main_json() -> str:
    return json.dumps(plano.proximo(), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(rodar())
