"""Execução isolada de código Python gerado pelo modelo.

Níveis (o modo `auto` escolhe o melhor disponível):
  bwrap    bubblewrap: namespaces novos (rede, PID, IPC, UTS, usuário), sistema somente-leitura,
           sem acesso ao $HOME nem ao repositório, /tmp vazio, morre junto com o processo pai.
  unshare  só corta a rede (`unshare -rn`). O código ainda enxerga e pode alterar seus arquivos.
  basico   só limites de CPU, memória, tamanho de arquivo e tempo.
Em todos: diretório temporário próprio, `python -I`, ambiente limpo, stdin fechado, rlimits.
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

NIVEIS = ("bwrap", "unshare", "basico")
DIR_TRABALHO = "/trabalho"  # onde o diretório temporário aparece dentro do bwrap


class SandboxIndisponivel(RuntimeError):
    pass


def _cfg() -> dict:
    from .config import hardware  # import tardio: config importa este módulo indiretamente
    return hardware()["sandbox"]


def _limites(mem_mb: int, cpu_s: int):
    def aplicar() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 2**20, mem_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 2**20, 16 * 2**20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()
    return aplicar


# Interpretador real (sem links simbólicos): uv/pyenv/conda instalam o python em ~/.local/... e expõem um
# link em outro lugar; dentro do bwrap só existe o que foi montado, então o link quebraria.
PYTHON = os.path.realpath(sys.executable)


def _prefixos_python() -> list[str]:
    """Diretórios que o interpretador precisa enxergar fora de /usr (pyenv/uv/conda moram no $HOME)."""
    dirs = {os.path.realpath(p) for p in (sys.base_prefix, sys.prefix)}
    dirs.add(os.path.dirname(os.path.dirname(PYTHON)))  # .../bin/python3 -> prefixo
    return sorted(d for d in dirs if d and d != "/" and not d.startswith("/usr"))


def _cmd_bwrap(tmp: str) -> list[str]:
    cmd = [shutil.which("bwrap") or "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
           "--hostname", "sandbox", "--ro-bind", "/usr", "/usr"]
    for d in ("/bin", "/sbin", "/lib", "/lib64", "/lib32"):
        if os.path.islink(d):
            cmd += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            cmd += ["--ro-bind", d, d]
    for arq in ("/etc/ld.so.cache", "/etc/localtime", "/etc/alternatives"):
        cmd += ["--ro-bind-try", arq, arq]
    for d in _prefixos_python():
        cmd += ["--ro-bind-try", d, d]
    cmd += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--bind", tmp, DIR_TRABALHO, "--chdir", DIR_TRABALHO]
    return cmd


def _funciona(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=10, stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@functools.cache
def disponiveis() -> tuple[str, ...]:
    """Níveis que funcionam nesta máquina, do mais forte para o mais fraco."""
    ok = []
    if shutil.which("bwrap"):
        with tempfile.TemporaryDirectory() as tmp:
            if _funciona(_cmd_bwrap(tmp) + [PYTHON, "-I", "-c", "pass"]):
                ok.append("bwrap")
    if shutil.which("unshare") and _funciona([shutil.which("unshare"), "-rn", "true"]):
        ok.append("unshare")
    ok.append("basico")
    return tuple(ok)


def diagnostico_bwrap() -> str:
    """Por que o bwrap não funciona aqui (texto para o usuário)."""
    exe = shutil.which("bwrap")
    if not exe:
        return "bubblewrap não instalado"
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = subprocess.run(_cmd_bwrap(tmp) + [PYTHON, "-I", "-c", "pass"], capture_output=True, text=True,
                               timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"bwrap não executou: {e}"
    if p.returncode == 0:
        return "ok"
    erro = (p.stderr or "").strip()[-300:]
    dica = ""
    if "uid map" in erro or "Permission denied" in erro or "Operation not permitted" in erro:
        dica = (" — o kernel está bloqueando namespaces de usuário. Ubuntu 24.04+: "
                "`sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0` (ou um perfil AppArmor para o bwrap); "
                "outras distros: confira kernel.unprivileged_userns_clone=1")
    elif "No such file" in erro:
        dica = f" — o interpretador {PYTHON} não ficou visível dentro da sandbox"
    return f"bwrap falhou: {erro}{dica}"


def nivel() -> str:
    """Nível efetivo segundo a configuração. Levanta SandboxIndisponivel se o pedido não existe."""
    cfg = _cfg()
    modo = cfg["modo"]
    disp = disponiveis()
    if modo == "auto":
        escolhido = disp[0]
    elif modo in NIVEIS:
        if modo not in disp:
            raise SandboxIndisponivel(f"sandbox '{modo}' pedida em config, mas indisponível (há: {', '.join(disp)})")
        escolhido = modo
    else:
        raise SandboxIndisponivel(f"modo de sandbox inválido: {modo!r} (use auto, {', '.join(NIVEIS)})")
    if cfg["exigir_isolamento"] and escolhido != "bwrap":
        raise SandboxIndisponivel("exigir_isolamento = true, mas o bwrap não funciona aqui "
                                  "(instale bubblewrap; veja scripts/instalar.sh)")
    return escolhido


def descrever() -> str:
    try:
        n = nivel()
    except SandboxIndisponivel as e:
        return f"INDISPONÍVEL: {e}"
    return {"bwrap": "bwrap (sem rede, sistema somente-leitura, sem acesso ao $HOME)",
            "unshare": "unshare (sem rede; o código ainda enxerga seus arquivos)",
            "basico": "básico (só limites de CPU/memória/tempo; SEM isolamento)"}[n]


def rodar(arquivos: dict[str, str], principal: str, timeout: float = 20.0,
          nivel_forcado: str | None = None) -> tuple[int, str]:
    """Grava `arquivos` num diretório temporário e roda `python -I principal` isolado."""
    n = nivel_forcado or nivel()
    cfg = _cfg()
    with tempfile.TemporaryDirectory(prefix="prova9060_") as tmp:
        raiz = Path(tmp).resolve()
        for nome, conteudo in arquivos.items():
            alvo = (raiz / nome).resolve()
            if raiz not in alvo.parents:
                return 1, f"caminho inválido: {nome}"
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text(conteudo, encoding="utf-8")
        casa = DIR_TRABALHO if n == "bwrap" else tmp
        env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
               "HOME": casa, "TMPDIR": "/tmp" if n == "bwrap" else tmp, "LANG": "C.UTF-8"}
        if n == "bwrap":
            prefixo = _cmd_bwrap(tmp)
        elif n == "unshare":
            prefixo = [shutil.which("unshare") or "unshare", "-rn"]
        else:
            prefixo = []
        cmd = prefixo + [PYTHON, "-I", principal]
        try:
            p = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=timeout,
                               preexec_fn=_limites(int(cfg["memoria_mb"]), int(cfg["cpu_s"])))
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
sys.stdout.write("\n@@RES@@" + json.dumps(res) + "\n")
'''


def _resultado(saida: str, rc: int) -> dict:
    if "@@RES@@" in saida:
        return json.loads(saida.rsplit("@@RES@@", 1)[1].strip().splitlines()[0])
    return {"carregou": False, "testes": [], "erro": saida[-800:] or f"rc={rc}"}


def testar_funcao(codigo: str, testes: list[str], preparo: str = "", timeout: float = 20.0) -> dict:
    arquivos = {"solucao.py": codigo, "testes.json": json.dumps(testes),
                "preparo.py": preparo, "_exec.py": _EXECUTOR_TESTES}
    rc, saida = rodar(arquivos, "_exec.py", timeout)
    res = _resultado(saida, rc)
    res["passou"] = sum(1 for _, ok, _ in res["testes"] if ok)
    res["total"] = len(testes)
    return res


_EXECUTOR_PREDICADO = r'''
import json, sys
ns = {"__name__": "predicado"}
exec(open("predicado.py", encoding="utf-8").read(), ns)
texto = open("resposta.txt", encoding="utf-8").read()
try:
    r = ns["ok"](texto)
    ok, det = (r if isinstance(r, tuple) else (bool(r), ""))
except Exception as e:
    ok, det = False, f"{type(e).__name__}: {e}"
sys.stdout.write("\n@@RES@@" + json.dumps({"ok": bool(ok), "detalhe": str(det)[:200]}) + "\n")
'''


def predicado(codigo: str, texto: str) -> tuple[bool, str]:
    """Roda `def ok(texto) -> bool | (bool, str)` (escrito na suíte) sobre a resposta do modelo, isolado."""
    rc, saida = rodar({"predicado.py": codigo, "resposta.txt": texto, "_p.py": _EXECUTOR_PREDICADO}, "_p.py", 10)
    if "@@RES@@" not in saida:
        return False, f"predicado falhou: {saida[-200:]}"
    res = json.loads(saida.rsplit("@@RES@@", 1)[1].strip().splitlines()[0])
    return res["ok"], res["detalhe"] or ("ok" if res["ok"] else "predicado falso")
