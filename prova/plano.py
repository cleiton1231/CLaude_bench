"""Próximo passo da série: lê o estado real (config, perfis, resultados, servidor, juiz) e diz o que fazer.

É o ponto de entrada do agente: `python3 -m prova proximo` (texto) ou `--json` (máquina). Não guarda
estado próprio; tudo é deduzido dos arquivos, então funciona depois de interrupções e retomadas.

Ações possíveis:
  rodar          executar `comando` (mecânico; o scripts/piloto.sh faz sozinho)
  julgar         dar notas 0–3 seguindo JULGAMENTO.md (precisa de inteligência)
  parecer        escrever resultados/<id>/parecer.md (precisa de inteligência)
  corrigir       consertar um arquivo que o agente escreveu (notas/parecer inválidos)
  bloqueado      parar e reportar ao humano (sanidade falhou, sandbox exigida ausente…)
  configurar     falta instalação/perfis (rodar instalar.sh ou criar perfis)
  aguardar       o piloto ou uma etapa em segundo plano ainda está rodando
  fim            série concluída: entregar o resumo ao humano
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from . import config

ORDEM_EXECUCAO = ("desempenho", "suites", "agente", "contexto", "consistencia", "criticos")
SCRIPT = {"desempenho": "03_desempenho.sh", "suites": "04_suites.sh", "agente": "05_agente.sh",
          "contexto": "06_contexto.sh", "consistencia": "07_consistencia.sh", "criticos": "11_criticos.sh"}
CONFERIR = {
    "01": "a saída termina com “pronto em Ns”; VRAM carregada abaixo de ~15,5 GiB",
    "02": "“sanidade OK”. Leia os AVISOS: tool call com erro = ferramentas/agente vão dar erro de servidor",
    "desempenho": "geração (tg) plausível: > 10 tok/s",
    "suites": "progresso caso a caso; linhas INFRA = erro do servidor (serão refeitas)",
    "agente": "8 cenários; INFRA = erro do servidor",
    "contexto": "nenhuma linha INFRA",
    "consistencia": "taxa de estáveis no final",
    "criticos": "“seguro k/N” por caso; qualquer k < N entra no parecer",
    "10": "“servidor parado”",
    "08": "o pacote foi gerado",
    "09": "“completo” na primeira linha; se INCOMPLETO, rode `prova proximo` de novo",
    "99": "a tabela comparativa",
}
SECOES_PARECER = ("**Veredito:**", "**Nota geral:**", "### Pontos fortes", "### Pontos fracos", "### Falhas graves",
                  "### Uso recomendado", "### Configuração", "### Comparação")


def _acao(acao: str, motivo: str, modelo: str | None = None, comando: list[str] | None = None,
          conferir: str = "", se_falhar: str = "", **extra) -> dict[str, Any]:
    return {"acao": acao, "modelo": modelo, "comando": comando or [], "motivo": motivo,
            "conferir": conferir, "se_falhar": se_falhar, **extra}


# ------------------------------------------------------------------ série e servidor
def serie() -> list[str]:
    """Modelos da série, em ordem: config/serie.toml (`modelos = [...]`) ou todos os perfis menos exemplo-*."""
    arq = Path(os.environ.get("PROVA_SERIE", config.RAIZ / "config" / "serie.toml"))
    if arq.exists():
        return list(config.ler_toml(arq).get("modelos", []))
    return sorted(p.stem for p in config.MODELOS.glob("*.toml") if not p.stem.startswith("exemplo-"))


def servidor_no_ar() -> bool:
    try:
        with urllib.request.urlopen(config.endpoint() + "/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def modelo_no_servidor() -> str | None:
    arq = config.RESULTADOS / ".servidor.id"
    return arq.read_text().strip() if arq.exists() else None


def _pid_vivo(arq: Path) -> int | None:
    try:
        pid = int(arq.read_text().strip())
        if pid == os.getpid():  # o próprio piloto perguntando
            return None
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def em_andamento() -> list[str]:
    """Piloto ou etapas em segundo plano (em_fundo.sh) ainda vivos."""
    vivos = []
    if _pid_vivo(config.RESULTADOS / ".piloto.pid"):
        vivos.append(f"piloto (log: {config.RESULTADOS / 'piloto.log'})")
    for pf in config.RESULTADOS.glob("*/logs/*.pid"):
        if _pid_vivo(pf):
            vivos.append(f"{pf.stem} de {pf.parent.parent.name} (log: {pf.with_suffix('.log')})")
    return vivos


# ------------------------------------------------------------------ pendências de um modelo
def pendencias_execucao(d: Path, sel: dict) -> dict[str, str]:
    """etapa -> motivo, para cada etapa de execução da seleção que ainda falta (em ordem)."""
    from .agente import carregar_cenarios, hash_cenario
    from .executor import ainda_vale, hash_caso, ler_jsonl, teve_erro_infra
    from .selecao import filtrar
    from .suites import todas

    falta: dict[str, str] = {}
    for etapa in ORDEM_EXECUCAO:
        if etapa not in sel["etapas"]:
            continue
        if etapa == "suites":
            faltando = []
            for s in todas(sel["suites"]):
                casos = filtrar(s["casos"], sel)
                hashes = {c["id"]: hash_caso(c) for c in s["casos"]}
                ok = {r["id"] for r in ler_jsonl(d / "suites" / f"{s['suite']}.jsonl") if ainda_vale(r, hashes)}
                faltando += [c["id"] for c in casos if c["id"] not in ok]
            if faltando:
                falta[etapa] = f"{len(faltando)} caso(s) sem resultado válido (novos, alterados ou erro de servidor)"
        elif etapa == "agente":
            cens = filtrar(carregar_cenarios(), sel)
            hashes = {c["id"]: hash_cenario(c) for c in carregar_cenarios()}
            ok = {r["id"] for r in ler_jsonl(d / "agente.jsonl") if ainda_vale(r, hashes)}
            faltando = [c["id"] for c in cens if c["id"] not in ok]
            if faltando:
                falta[etapa] = f"{len(faltando)} cenário(s) sem resultado válido"
        elif etapa == "contexto":
            regs = ler_jsonl(d / "contexto.jsonl")
            if not regs:
                falta[etapa] = "contexto longo ainda não medido"
            elif any(teve_erro_infra(r) for r in regs):
                falta[etapa] = "houve erro de servidor no contexto longo"
        else:
            arq = {"desempenho": "desempenho.json", "consistencia": "consistencia.json",
                   "criticos": "criticos.json"}[etapa]
            if not (d / arq).exists():
                falta[etapa] = f"{arq} ainda não existe"
    return falta


def juiz_pendente(d: Path, sel: dict) -> tuple[list[str], list[str]]:
    """(casos de juiz sem nota válida, problemas no notas_juiz.json)."""
    from .executor import teve_erro_infra
    from .pontuacao import carregar_registros, na_selecao
    regs = [r for r in carregar_registros(d) if na_selecao(r, sel) and r["avaliacao"] == "juiz"
            and not teve_erro_infra(r)]
    arq = d / "notas_juiz.json"
    if not arq.exists():
        return [r["id"] for r in regs], []
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [r["id"] for r in regs], [f"notas_juiz.json não é JSON válido: {e}"]
    notas = dados.get("casos", dados) if isinstance(dados, dict) else {}
    problemas, faltam = [], []
    for r in regs:
        n = (notas.get(r["id"]) or {}).get("nota") if isinstance(notas.get(r["id"]), dict) else None
        if n is None:
            faltam.append(r["id"])
        elif not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 3:
            problemas.append(f"{r['id']}: nota {n!r} inválida (use inteiro 0–3)")
        elif not str(notas[r["id"]].get("motivo", "")).strip():
            problemas.append(f"{r['id']}: falta o motivo")
    return faltam, problemas


def problemas_parecer(d: Path) -> list[str]:
    arq = d / "parecer.md"
    if not arq.exists():
        return ["parecer.md não existe"]
    texto = arq.read_text(encoding="utf-8")
    faltam = [s for s in SECOES_PARECER if s not in texto]
    probs = [f"falta a seção {s}" for s in faltam]
    if not re.search(r"\*\*Confiança:\*\*\s*(alta|média|media|baixa)", texto, re.I):
        probs.append("falta **Confiança:** alta | média | baixa")
    return probs


def _mtime(*arqs: Path) -> float:
    return max((a.stat().st_mtime for a in arqs if a.exists()), default=0.0)


def placar_desatualizado(d: Path) -> bool:
    placar = d / "placar.json"
    if not placar.exists():
        return True
    entradas = [*(d / "suites").glob("*.jsonl"), d / "agente.jsonl", d / "contexto.jsonl", d / "notas_juiz.json",
                d / "parecer.md", d / "criticos.json", d / "consistencia.json", d / "desempenho.json"]
    return _mtime(*entradas) > placar.stat().st_mtime


# ------------------------------------------------------------------ decisão
def proximo() -> dict[str, Any]:
    from . import sandbox, selecao

    vivos = em_andamento()
    if vivos:
        return _acao("aguardar", "há execução em segundo plano: " + "; ".join(vivos),
                     comando=["python3", "-m", "prova", "proximo"],
                     conferir="espere alguns minutos e rode `prova proximo` de novo")
    try:
        sel = selecao.carregar()
    except selecao.SelecaoInvalida as e:
        return _acao("bloqueado", f"seleção inválida: {e}", se_falhar="peça ao humano para corrigir config/selecao.toml")
    srv = config.hardware()["servidor"]
    if not os.access(os.path.expanduser(srv["binario"]), os.X_OK):
        return _acao("configurar", f"llama-server não encontrado em {srv['binario']}",
                     comando=["scripts/instalar.sh", "--auto"],
                     se_falhar="peça ao humano o caminho do llama-server: scripts/instalar.sh --auto --bin CAMINHO")
    precisa_codigo = bool({"suites", "agente", "consistencia", "criticos"} & set(sel["etapas"]))
    if precisa_codigo:
        try:
            sandbox.nivel()
        except sandbox.SandboxIndisponivel as e:
            return _acao("bloqueado", str(e), se_falhar="reporte ao humano (veja `python3 -m prova sandbox`)")
    modelos = serie()
    if not modelos:
        return _acao("configurar", "nenhum perfil de modelo em config/modelos/",
                     comando=["scripts/instalar.sh", "--auto", "--modelos", "<PASTA_DOS_GGUF>"],
                     se_falhar="peça ao humano a pasta dos .gguf ou crie com `python3 -m prova novo-perfil ARQ.gguf`")
    faltando_perfil = [m for m in modelos if not (config.MODELOS / f"{m}.toml").exists()]
    if faltando_perfil:
        return _acao("bloqueado", f"config/serie.toml cita perfis que não existem: {', '.join(faltando_perfil)}")

    no_ar = servidor_no_ar()
    atual = modelo_no_servidor() if no_ar else None

    # 1ª passada: toda a parte mecânica (GPU) de todos os modelos, para o piloto rodar sem parar
    for mid in modelos:
        d = config.RESULTADOS / mid
        falta = pendencias_execucao(d, sel)
        if not falta:
            continue
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        if atual and atual != mid:
            return _acao("rodar", f"o servidor está com {atual}; {mid} precisa dele", mid,
                         ["scripts/10_parar_modelo.sh"], CONFERIR["10"])
        if not (no_ar and atual == mid):
            return _acao("rodar", f"{mid}: faltam {', '.join(falta)}; servidor desligado", mid,
                         ["scripts/01_subir_modelo.sh", str(config.MODELOS / f"{mid}.toml")], CONFERIR["01"],
                         f"leia {d / 'logs' / 'llama-server.log'}; falha de alocação = reduza ctx no perfil")
        san = meta.get("sanidade")
        if not san:
            return _acao("rodar", f"{mid}: servidor recém-carregado, falta a sanidade", mid,
                         ["scripts/02_sanidade.sh", mid], CONFERIR["02"])
        if not san.get("ok"):
            return _acao("bloqueado", f"{mid}: sanidade falhou: {'; '.join(san.get('problemas', []))}", mid,
                         ["scripts/10_parar_modelo.sh"],
                         se_falhar="pare o servidor e reporte ao humano; não continue com este modelo. "
                                   "Para pular o modelo, tire-o de config/serie.toml")
        etapa = next(iter(falta))
        return _acao("rodar", f"{mid}: {falta[etapa]}", mid, [f"scripts/{SCRIPT[etapa]}", mid], CONFERIR[etapa],
                     "rode o mesmo comando de novo (retoma de onde parou); se repetir, reporte as últimas linhas",
                     etapa=etapa)
    if no_ar and atual:
        return _acao("rodar", "execução de todos os modelos concluída; liberar a VRAM", atual,
                     ["scripts/10_parar_modelo.sh"], CONFERIR["10"])

    # Depois, em ondas: cada onda faz o mecânico de TODOS os modelos antes de pedir o trabalho do agente,
    # para o piloto adiantar o máximo e o agente julgar/escrever tudo em sequência.
    estado = {m: (config.RESULTADOS / m, *juiz_pendente(config.RESULTADOS / m, sel)) for m in modelos}

    for mid, (d, sem_nota, _) in estado.items():  # onda 1: pacotes do juiz
        if sem_nota and _mtime(d / "pacote_juiz.md") < _mtime(*(d / "suites").glob("*.jsonl")):
            return _acao("rodar", f"{mid}: {len(sem_nota)} caso(s) de juiz; gerar o pacote", mid,
                         ["scripts/08_pacote_juiz.sh", mid], CONFERIR["08"])
    for mid, (d, sem_nota, probs_notas) in estado.items():  # onda 2: julgamento (agente)
        if probs_notas:
            return _acao("corrigir", f"{mid}: notas_juiz.json com problemas", mid,
                         problemas=probs_notas, arquivo=str(d / "notas_juiz.json"))
        if sem_nota:
            return _acao("julgar", f"{mid}: {len(sem_nota)} caso(s) aguardando nota", mid,
                         conferir="todos os casos do pacote com nota inteira 0–3 e motivo",
                         ler=["JULGAMENTO.md §1–3", str(d / "pacote_juiz.md")],
                         escrever=str(d / "notas_juiz.json"), modelo_arquivo=str(d / "notas_juiz.modelo.json"),
                         casos=sem_nota)
    for mid, (d, _, _) in estado.items():  # onda 3: placares
        if placar_desatualizado(d):
            return _acao("rodar", f"{mid}: calcular o placar", mid, ["scripts/09_pontuar.sh", mid], CONFERIR["09"])
    comp = config.RESULTADOS / "comparativo.md"
    placares = [config.RESULTADOS / m / "placar.json" for m in modelos]
    if len(modelos) > 1 and _mtime(comp) < _mtime(*placares):  # onda 4: comparativo (o parecer compara)
        return _acao("rodar", "placares prontos; gerar o comparativo", None, ["scripts/99_comparar.sh"],
                     CONFERIR["99"])
    for mid, (d, _, _) in estado.items():  # onda 5: pareceres (agente)
        probs = problemas_parecer(d)
        if probs == ["parecer.md não existe"]:
            ler = ["JULGAMENTO.md §4–8", str(d / "relatorio.md")] + ([str(comp)] if comp.exists() else [])
            return _acao("parecer", f"{mid}: placar pronto; falta o parecer", mid,
                         conferir="seções exatas do JULGAMENTO.md §8", ler=ler, escrever=str(d / "parecer.md"))
        if probs:
            return _acao("corrigir", f"{mid}: parecer.md incompleto", mid, problemas=probs, arquivo=str(d / "parecer.md"))
    # os pareceres entram no relatório: a onda 3 refaz os placares e a 4 o comparativo na próxima chamada

    return _acao("fim", f"série concluída ({len(modelos)} modelo(s))",
                 conferir="entregue ao humano: tabela de resultados/comparativo.md, uma linha de veredito por "
                          "modelo, críticos falhos com o “seguro k/N”, erros de servidor e duração (AGENTS.md)",
                 ler=[str(comp)] if comp.exists() else [str(config.RESULTADOS / m / "relatorio.md") for m in modelos])


def progresso() -> list[dict]:
    """Resumo por modelo, para o cabeçalho do `proximo`."""
    from . import selecao
    sel = selecao.carregar()
    linhas = []
    for mid in serie():
        d = config.RESULTADOS / mid
        if not (d / "meta.json").exists():
            linhas.append({"modelo": mid, "estado": "não iniciado"})
            continue
        falta = pendencias_execucao(d, sel)
        if falta:
            estado = "executando: falta " + ", ".join(falta)
        elif juiz_pendente(d, sel)[0]:
            estado = "aguardando juiz"
        elif problemas_parecer(d):
            estado = "aguardando parecer"
        else:
            p = json.loads((d / "placar.json").read_text()) if (d / "placar.json").exists() else {}
            estado = f"concluído · nota {p.get('nota_geral', '?')}"
        linhas.append({"modelo": mid, "estado": estado})
    return linhas


def texto(a: dict, prog: list[dict], rodada: str) -> str:
    L = [f"SÉRIE · rodada {rodada}"]
    for p in prog:
        L.append(f"  {p['modelo']:<28} {p['estado']}")
    L += ["", f"PRÓXIMA AÇÃO: {a['acao'].upper()}" + (f" ({a['modelo']})" if a.get("modelo") else ""),
          f"  por quê: {a['motivo']}"]
    if a["comando"]:
        L.append("  comando: " + " ".join(a["comando"]))
    for chave, rotulo in (("ler", "leia"), ("escrever", "escreva"), ("modelo_arquivo", "modelo"),
                          ("arquivo", "arquivo")):
        if a.get(chave):
            v = a[chave]
            L.append(f"  {rotulo}: " + (", ".join(v) if isinstance(v, list) else v))
    if a.get("problemas"):
        L += ["  problemas:"] + [f"    - {p}" for p in a["problemas"]]
    if a["conferir"]:
        L.append(f"  depois confira: {a['conferir']}")
    if a["se_falhar"]:
        L.append(f"  se falhar: {a['se_falhar']}")
    L += ["", "Rode `python3 -m prova proximo` de novo depois de cada ação."]
    return "\n".join(L)
