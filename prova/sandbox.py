"""Execução isolada (best-effort) de código Python gerado pelo modelo.

Camadas: subprocess com `python -I`, diretório temporário, limites de CPU/memória/arquivo
(rlimit) e, se o kernel permitir, `unshare -rn` para cortar a rede.
Não é uma sandbox de segurança forte: rode a prova numa máquina/usuário que você aceite arriscar.
"""

from __future__ import annotations

import functools
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MEM_BYTES = 1024 * 1024 * 1024
CPU_S = 20


def _limites() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_S, CPU_S))
    resource.setrlimit(resource.RLIMIT_AS, (MEM_BYTES, MEM_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    os.setsid()


@functools.cache
def _prefixo_rede() -> list[str]:
    exe = shutil.which("unshare")
    if not exe:
        return []
    try:
        ok = subprocess.run([exe, "-rn", "true"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    return [exe, "-rn"] if ok else []


def rodar(arquivos: dict[str, str], principal: str, timeout: float = 20.0) -> tuple[int, str]:
    """Grava `arquivos` num diretório temporário e roda `python -I principal` lá dentro."""
    with tempfile.TemporaryDirectory(prefix="prova9060_") as tmp:
        raiz = Path(tmp)
        for nome, conteudo in arquivos.items():
            alvo = (raiz / nome).resolve()
            if raiz.resolve() not in alvo.parents:
                return 1, f"caminho inválido: {nome}"
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text(conteudo, encoding="utf-8")
        cmd = _prefixo_rede() + [sys.executable, "-I", principal]
        env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
               "HOME": tmp, "LANG": "C.UTF-8"}
        try:
            p = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=timeout, preexec_fn=_limites)
            return p.returncode, (p.stdout + p.stderr)[-6000:]
        except subprocess.TimeoutExpired:
            return 124, "TIMEOUT"


_EXECUTOR_TESTES = r'''
import json, sys, traceback
ns = {"__name__": "solucao"}
res = {"carregou": False, "testes": [], "erro": ""}
try:
    exec(compile(open("solucao.py", encoding="utf-8").read(), "solucao.py", "exec"), ns)
    res["carregou"] = True
except BaseException as e:
    res["erro"] = "".join(traceback.format_exception_only(type(e), e)).strip()
if res["carregou"]:
    preparo = open("preparo.py", encoding="utf-8").read()
    if preparo.strip():
        exec(preparo, ns)
    for t in json.load(open("testes.json", encoding="utf-8")):
        try:
            exec(t, ns)
            res["testes"].append([t, True, ""])
        except BaseException as e:
            res["testes"].append([t, False, (type(e).__name__ + ": " + str(e))[:200]])
print("@@RES@@" + json.dumps(res))
'''


def testar_funcao(codigo: str, testes: list[str], preparo: str = "",
                  timeout: float = 20.0) -> dict:
    arquivos = {"solucao.py": codigo, "testes.json": json.dumps(testes),
                "preparo.py": preparo, "_exec.py": _EXECUTOR_TESTES}
    rc, saida = rodar(arquivos, "_exec.py", timeout)
    if "@@RES@@" in saida:
        res = json.loads(saida.split("@@RES@@", 1)[1].strip().splitlines()[0])
    else:
        res = {"carregou": False, "testes": [], "erro": saida[-800:] or f"rc={rc}"}
    res["passou"] = sum(1 for _, ok, _ in res["testes"] if ok)
    res["total"] = len(testes)
    return res
