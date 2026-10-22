"""CLI: python3 -m prova <comando>. Os scripts em scripts/ chamam estes comandos."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
import time
from pathlib import Path

from . import config, gpu
from .cliente import Cliente, ErroCliente


def _cliente(modelo_id: str) -> tuple[Cliente, dict]:
    perf = config.perfil_do_resultado(modelo_id)
    timeout = config.hardware()["bench"].get("timeout_caso_s", 300)
    cli = Cliente(config.endpoint(), timeout=timeout * (2 if perf["pensamento"] else 1),
                  pensamento=perf["pensamento"], template_kwargs=perf.get("template_kwargs"),
                  folga_pensamento=perf.get("folga_pensamento", 2048 if perf["pensamento"] else 0))
    try:
        cli.saude()
    except ErroCliente as e:
        sys.exit(f"ERRO: servidor não responde em {config.endpoint()} ({e}). Rode 01_subir_modelo.sh.")
    return cli, perf


def _etapa(modelo_id: str, nome: str, t0: float, **extra) -> None:
    m = config.meta(modelo_id)
    etapas = m.get("etapas", {})
    etapas[nome] = {"fim": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "minutos": round((time.monotonic() - t0) / 60, 2), **extra}
    config.salvar_meta(modelo_id, etapas=etapas)
    print(f"== etapa '{nome}' concluída em {etapas[nome]['minutos']} min")


def cmd_perfil(a) -> int:
    p = config.perfil(a.perfil)
    hw = config.hardware()
    srv = hw["servidor"]
    flags = ["-ngl", str(p["ngl"]), "--ctx-size", str(p["ctx"]), "--jinja",
             "-ctk", p["kv_cache"], "-ctv", p["kv_cache"], "-fa", "on" if p["flash_attn"] else "off",
             "--seed", str(hw["bench"]["seed"]), "--temp", "0", "--parallel", "1"]
    flags += [str(x) for x in p["args_extra"]]
    linhas = {
        "PROVA_ID": p["id"], "PROVA_NOME": p["nome"],
        "PROVA_GGUF": os.path.expanduser(p["gguf"]),
        "PROVA_BIN": os.path.expanduser(srv["binario"]),
        "PROVA_HOST": srv["host"], "PROVA_PORTA": str(srv["porta"]),
    }
    for k, v in linhas.items():
        print(f"{k}={shlex.quote(v)}")
    print("PROVA_FLAGS=(" + " ".join(shlex.quote(f) for f in flags) + ")")
    amb = srv.get("ambiente", {})
    print("PROVA_AMBIENTE=(" + " ".join(shlex.quote(f"{k}={v}") for k, v in amb.items()) + ")")
    return 0


def cmd_servidor(a) -> int:
    srv = config.hardware()["servidor"]
    print(f"PROVA_HOST={shlex.quote(srv['host'])}\nPROVA_PORTA={srv['porta']}")
    return 0


def cmd_vram(a) -> int:
    v = gpu.vram_usada()
    print("" if v is None else v)
    return 0


def cmd_registrar_carga(a) -> int:
    p = config.perfil(a.perfil)
    config.salvar_meta(p["id"], perfil=p, segundos_carga=a.segundos,
                       vram_base_gib=float(a.vram_base) if a.vram_base else None,
                       vram_carregado_gib=gpu.vram_usada(), gpu=gpu.leitura(),
                       carregado_em=time.strftime("%Y-%m-%dT%H:%M:%S"),
                       seed=config.hardware()["bench"]["seed"], etapas={},
                       sanidade=None)  # servidor novo: a sanidade precisa ser refeita
    m = config.meta(p["id"])
    print(f"carregado: VRAM {m.get('vram_base_gib')} -> {m.get('vram_carregado_gib')} GiB em {a.segundos}s")
    vram_total = config.hardware()["gpu"].get("vram_gib", 16)
    if m.get("vram_carregado_gib") and m["vram_carregado_gib"] > vram_total - 0.4:
        print("AVISO: VRAM quase cheia — risco de transbordar para RAM (GTT) e derrubar a velocidade. "
              "Reduza ctx, use KV q8_0/q4_0 ou --n-cpu-moe.")
    return 0


def cmd_sanidade(a) -> int:
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    problemas, avisos = [], []
    props = cli.propriedades()
    ctx_srv = (props.get("default_generation_settings") or {}).get("n_ctx") or props.get("n_ctx")
    if ctx_srv and int(ctx_srv) < perf["ctx"]:
        avisos.append(f"servidor com n_ctx={ctx_srv} < perfil ctx={perf['ctx']}")
    r = cli.chat([{"role": "user", "content": "Responda apenas com a palavra: PRONTO"}], 32)
    if r.erro:
        problemas.append(f"chat falhou: {r.erro}")
    elif "pronto" not in r.texto.lower():
        problemas.append(f"resposta inesperada ao smoke: {r.texto[:120]!r}")
    if r.raciocinio and not perf["pensamento"]:
        avisos.append("o modelo emitiu raciocínio com pensamento=false (template ignora enable_thinking?)")
    from .ferramentas import schemas
    rt = cli.chat([{"role": "user", "content": "Qual o clima em Curitiba?"}], 128,
                  ferramentas=schemas(["obter_clima"]))
    if rt.erro:
        avisos.append(f"o servidor deu ERRO ao processar uma tool call ({rt.erro[:120]}). Template/parser de "
                      "ferramentas quebrado: ferramentas e agente vão sair como erro de servidor. Tente um "
                      "llama.cpp mais novo ou --chat-template-file com o template oficial do modelo.")
    elif not rt.chamadas:
        avisos.append("smoke de ferramenta sem tool_call (servidor sem --jinja ou modelo sem suporte); "
                      "as categorias ferramentas/agente vão pontuar baixo")
    try:
        cli.contar_tokens("teste")
    except ErroCliente as e:
        problemas.append(f"/tokenize indisponível: {e}")
    res = {"ok": not problemas, "problemas": problemas, "avisos": avisos, "tg_tps_smoke": r.tg_tps,
           "ctx_servidor": ctx_srv}
    config.salvar_meta(a.modelo, sanidade=res)
    for p in problemas:
        print("PROBLEMA:", p)
    for w in avisos:
        print("AVISO:", w)
    _etapa(a.modelo, "sanidade", t0)
    print("sanidade OK" if res["ok"] else "sanidade FALHOU — não prossiga")
    return 0 if res["ok"] else 1


def cmd_desempenho(a) -> int:
    from .desempenho import medir
    if _pular(a.modelo, "desempenho", _selecao()):
        return 0
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    res = medir(cli, perf["ctx"], config.hardware()["bench"]["seed"])
    (config.dir_modelo(a.modelo) / "desempenho.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    _etapa(a.modelo, "desempenho", t0)
    return 0


def _selecao(a=None) -> dict:
    from . import selecao
    try:
        return selecao.carregar()
    except selecao.SelecaoInvalida as e:
        sys.exit(f"ERRO na seleção de testes: {e}")


def _pular(modelo_id: str, etapa: str, sel: dict) -> bool:
    """Grava a seleção usada e diz se a etapa está desligada na rodada."""
    from .selecao import resumo
    config.salvar_meta(modelo_id, rodada=resumo(sel))
    if etapa not in sel["etapas"]:
        print(f"== etapa '{etapa}' desligada na rodada '{sel['nome']}' — pulando")
        return True
    return False


def _exigir_sandbox(modelo_id: str) -> None:
    from . import sandbox
    try:
        nivel = sandbox.nivel()
    except sandbox.SandboxIndisponivel as e:
        sys.exit(f"ERRO: {e}")
    config.salvar_meta(modelo_id, sandbox=nivel)
    print(f"sandbox: {sandbox.descrever()}")


def cmd_suites(a) -> int:
    from .executor import rodar_suite
    from .selecao import filtrar
    from .suites import todas
    sel = _selecao()
    if a.so:
        sel["suites"] = a.so.split(",")
    if _pular(a.modelo, "suites", sel):
        return 0
    _exigir_sandbox(a.modelo)
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    seed = config.hardware()["bench"]["seed"]
    d = config.dir_modelo(a.modelo) / "suites"
    for s in todas(sel["suites"]):
        casos = filtrar(s["casos"], sel)
        if not casos:
            continue
        print(f"\n## suíte {s['suite']} v{s['versao']} ({len(casos)} de {len(s['casos'])} casos)")
        rodar_suite(cli, s, d / f"{s['suite']}.jsonl", seed, perf["mult_tokens"], a.refazer, casos)
    _etapa(a.modelo, "suites", t0)
    return 0


def cmd_agente(a) -> int:
    from .agente import carregar_cenarios, rodar_todos
    from .selecao import filtrar
    sel = _selecao()
    if _pular(a.modelo, "agente", sel):
        return 0
    _exigir_sandbox(a.modelo)
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    rodar_todos(cli, config.dir_modelo(a.modelo) / "agente.jsonl", config.hardware()["bench"]["seed"],
                perf["mult_tokens"], a.refazer, filtrar(carregar_cenarios(), sel))
    _etapa(a.modelo, "agente", t0)
    return 0


def cmd_contexto(a) -> int:
    from .contexto import rodar
    sel = _selecao()
    if _pular(a.modelo, "contexto", sel):
        return 0
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    _, pico = rodar(cli, perf["ctx"], config.hardware()["bench"]["seed"],
                    config.dir_modelo(a.modelo) / "contexto.jsonl", perf["mult_tokens"], sel)
    _etapa(a.modelo, "contexto", t0, vram_pico_gib=pico)
    return 0


def cmd_consistencia(a) -> int:
    from .consistencia import rodar
    sel = _selecao()
    if _pular(a.modelo, "consistencia", sel):
        return 0
    _exigir_sandbox(a.modelo)
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    res = rodar(cli, config.dir_modelo(a.modelo), config.hardware()["bench"]["seed"], perf["mult_tokens"], sel)
    print(f"estáveis: {res['taxa_estavel'] * 100:.0f}%")
    _etapa(a.modelo, "consistencia", t0)
    return 0


def cmd_criticos(a) -> int:
    from .criticos import rodar
    sel = _selecao()
    if _pular(a.modelo, "criticos", sel):
        return 0
    _exigir_sandbox(a.modelo)
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    res = rodar(cli, config.dir_modelo(a.modelo), config.hardware()["bench"]["seed"], sel, perf["mult_tokens"])
    print(f"taxa segura: {res['taxa_segura'] * 100:.0f}%")
    _etapa(a.modelo, "criticos", t0)
    return 0


def cmd_pacote(a) -> int:
    from .pacote import gerar
    out, n = gerar(config.dir_modelo(a.modelo))
    print(f"pacote: {out} ({n} casos para julgar)")
    print(f"modelo de notas: {out.parent / 'notas_juiz.modelo.json'}")
    return 0


def cmd_pontuar(a) -> int:
    from .pontuacao import calcular, relatorio_md
    from .selecao import resumo
    d = config.dir_modelo(a.modelo)
    config.salvar_meta(a.modelo, rodada=resumo(_selecao()))  # o placar segue a seleção vigente
    p = calcular(d)
    (d / "placar.json").write_text(json.dumps(p, indent=2, ensure_ascii=False))
    (d / "relatorio.md").write_text(relatorio_md(p), encoding="utf-8")
    print(f"rodada {p['rodada']} · nota geral {p['nota_geral']} ({p['faixa_geral']}) — "
          f"{'completo' if p['completo'] else 'INCOMPLETO'}")
    for nome, c in sorted(p["categorias"].items()):
        extra = ("  [incoerente]" if c["incoerente"] else "") + \
                (f"  [{c['erros_infra']} erro(s) de servidor]" if c.get("erros_infra") else "")
        print(f"  {nome:<12} {c['nota']:>5}  {c['faixa']:<11} n={c['n']}{extra}")
    if p["faltando"]:
        print(f"  sem resultado: {', '.join(p['faltando'])}")
    if p["nao_rodados"]:
        print(f"  {len(p['nao_rodados'])} casos ainda não rodados (rode a etapa de novo; só eles serão executados)")
    if p["pendentes_juiz"]:
        print(f"  pendentes de juiz: {len(p['pendentes_juiz'])}")
    if p["erros_infra"]:
        print(f"  ERROS DE SERVIDOR (fora da nota): {', '.join(p['erros_infra'])}")
    if p["criticos_falhos"]:
        print(f"  CRÍTICOS FALHOS: {', '.join(p['criticos_falhos'])}")
    print(f"relatório: {d / 'relatorio.md'}")
    return 0


def cmd_comparar(a) -> int:
    from .pontuacao import comparativo_md
    placares = [json.loads(p.read_text()) for p in sorted(config.RESULTADOS.glob("*/placar.json"))
                if p.parent.name != "ensaio"]
    if not placares:
        sys.exit("nenhum placar.json encontrado; rode 09_pontuar.sh antes")
    out = config.RESULTADOS / "comparativo.md"
    out.write_text(comparativo_md(placares), encoding="utf-8")
    print(out.read_text())
    return 0


# Fração do teto de tokens que as respostas usam na prática. Calibrado com uma rodada real na 9060 XT
# (Qwen3.5 4B, v1 das suítes: 9,6 min a 53 tok/s). Modelos prolixos ficam acima disso.
FATOR_TIPICO = 0.2
TOKENS_TIPICOS_CENARIO = 1500


def estimativa(sel: dict, mult: float = 1.0, folga: int = 0, tps: float = 30.0) -> dict:
    """Minutos estimados por etapa para a seleção (geração domina; prefill entra como constante)."""
    from .agente import carregar_cenarios
    from .criticos import casos_criticos
    from .selecao import filtrar
    from .suites import todas

    def tok_caso(c):
        rodadas = 1 + len(c.get("turnos_seguintes", [])) + (1 if c.get("ferramentas") else 0)
        return c["max_tokens"] * rodadas * mult * FATOR_TIPICO + folga * rodadas * 0.5

    def minutos(tok):
        return tok / tps / 60

    et: dict[str, float] = {}
    por_suite = {}
    if "suites" in sel["etapas"]:
        for s in todas(sel["suites"]):
            casos = filtrar(s["casos"], sel)
            if casos:
                por_suite[s["suite"]] = (len(casos), minutos(sum(tok_caso(c) for c in casos)))
        et["suites"] = sum(m for _, m in por_suite.values())
    cen = filtrar(carregar_cenarios(), sel)
    if "agente" in sel["etapas"]:
        et["agente"] = minutos(len(cen) * TOKENS_TIPICOS_CENARIO * mult)
    if "desempenho" in sel["etapas"]:
        et["desempenho"] = 1.5 + minutos(6 * 256)
    if "contexto" in sel["etapas"]:
        et["contexto"] = 2.5
    if "consistencia" in sel["etapas"]:
        cons = [c for s in todas(sel["suites"]) for c in filtrar(s["casos"], sel)
                if c["consistencia"] and c["avaliacao"] == "auto"]
        et["consistencia"] = minutos(2 * sum(tok_caso(c) for c in cons))
    if "criticos" in sel["etapas"]:
        casos, cens = casos_criticos(sel)
        et["criticos"] = minutos(sel["repeticoes_criticos"] * sum(tok_caso(c) for c in casos)
                                 + sel["repeticoes_criticos_agente"] * len(cens) * TOKENS_TIPICOS_CENARIO * mult)
    return {"etapas": et, "suites": por_suite, "total": sum(et.values()) + 1.0}  # +1 min: carga do modelo


def cmd_estimar(a) -> int:
    sel = _selecao()
    perf = config.perfil(a.perfil) if a.perfil else {"mult_tokens": 1.0, "folga_pensamento": 0}
    tps = a.tps or config.hardware()["bench"].get("tok_s_referencia", 30)
    e = estimativa(sel, perf["mult_tokens"], perf["folga_pensamento"], tps)
    print(f"rodada: {sel['nome']} · referência {tps:g} tok/s")
    for nome, (n, m) in e["suites"].items():
        print(f"  suíte {nome:<12} {n:>3} casos  ~{m:4.1f} min")
    for nome, m in e["etapas"].items():
        print(f"  etapa {nome:<12}            ~{m:4.1f} min")
    print(f"total estimado: ~{e['total']:.0f} min por modelo")
    medidos = []
    for arq in sorted(config.RESULTADOS.glob("*/meta.json")):
        et = json.loads(arq.read_text()).get("etapas", {})
        if et:
            medidos.append(f"{arq.parent.name} {sum(x['minutos'] for x in et.values()):.0f} min")
    if medidos:
        print("medido em rodadas anteriores: " + " · ".join(medidos))
    return 0


def cmd_rodada(a) -> int:
    from .selecao import categorias_esperadas, resumo, rodadas
    sel = _selecao()
    if a.nome:
        print(sel["nome"])
        return 0
    print(json.dumps(resumo(sel), indent=2, ensure_ascii=False))
    print("categorias:", ", ".join(categorias_esperadas(sel)) or "(nenhuma — só medições)")
    print("\nrodadas disponíveis:")
    for nome, r in rodadas().items():
        print(f"  {nome:<11} {r.get('descricao', '')}")
    return 0


def cmd_escolher(a) -> int:
    """Escolha interativa (ou direta: `prova escolher rapida`) gravada em config/selecao.toml."""
    from . import selecao
    from .suites import nomes_suites
    presets = selecao.rodadas()
    nomes = list(presets)
    if a.rodada:
        if a.rodada not in presets:
            sys.exit(f"rodada '{a.rodada}' não existe (há: {', '.join(nomes)})")
        arq = selecao.gravar(a.rodada, {"suites": a.suites.split(",")} if a.suites else None)
        print(f"gravado {arq}")
        return cmd_estimar(argparse.Namespace(perfil=None, tps=None))
    print("Rodadas disponíveis:")
    for i, n in enumerate(nomes, 1):
        print(f"  {i}) {n:<11} {presets[n].get('descricao', '')}")
    r = input(f"Escolha [1-{len(nomes)}] (enter = completa): ").strip()
    nome = nomes[int(r) - 1] if r.isdigit() and 1 <= int(r) <= len(nomes) else "completa"
    ajustes = {}
    if input("Ajustar quais suítes entram? [s/N] ").strip().lower().startswith("s"):
        todas_s = nomes_suites()
        for i, s in enumerate(todas_s, 1):
            print(f"  {i}) {s}")
        r = input("Números separados por vírgula (enter = todas): ").strip()
        if r:
            ajustes["suites"] = [todas_s[int(x) - 1] for x in r.split(",") if x.strip().isdigit()
                                 and 1 <= int(x) <= len(todas_s)]
    arq = selecao.gravar(nome, ajustes)
    print(f"\ngravado {arq}")
    return cmd_estimar(argparse.Namespace(perfil=None, tps=None))


def cmd_etapa_ativa(a) -> int:
    return 0 if a.etapa in _selecao()["etapas"] else 1


def cmd_sandbox(a) -> int:
    from . import sandbox
    print("níveis que funcionam aqui:", ", ".join(sandbox.disponiveis()))
    print("modo configurado:", config.hardware()["sandbox"]["modo"])
    print("nível efetivo:", sandbox.descrever())
    if "bwrap" not in sandbox.disponiveis():
        print("bwrap:", sandbox.diagnostico_bwrap())
        if not shutil.which("bwrap"):
            print("Recomendado: instale o bubblewrap (Fedora: sudo dnf install bubblewrap · "
                  "Arch: sudo pacman -S bubblewrap · Debian/Ubuntu: sudo apt install bubblewrap)")
    return 0


def cmd_novo_perfil(a) -> int:
    from .perfis import gravar_perfil
    for g in a.gguf:
        arq, avisos = gravar_perfil(Path(g).expanduser(), ctx=a.ctx, forcar=a.forcar)
        print(f"{'criado' if arq else 'já existe'}: {arq or g}")
        for w in avisos:
            print("  aviso:", w)
    return 0


def cmd_proximo(a) -> int:
    from . import plano
    acao = plano.proximo()
    if a.json:
        print(json.dumps({**acao, "progresso": plano.progresso()}, ensure_ascii=False, indent=2))
    else:
        print(plano.texto(acao, plano.progresso(), _selecao()["nome"]))
    return 0


def cmd_piloto(a) -> int:
    from . import piloto
    return piloto.rodar(a.max_passos)


def cmd_validar(a) -> int:
    from .agente import carregar_cenarios
    from .suites import todas
    total = 0
    for s in todas():
        difs = {d: sum(c["dificuldade"] == d for c in s["casos"]) for d in ("facil", "medio", "dificil")}
        juiz = sum(c["avaliacao"] == "juiz" for c in s["casos"])
        print(f"{s['suite']:<14} {len(s['casos']):>3} casos  {difs}  juiz={juiz}")
        total += len(s["casos"])
    cen = carregar_cenarios()
    print(f"{'agente':<14} {len(cen):>3} cenários")
    print(f"total: {total} casos + {len(cen)} cenários + contexto gerado")
    _selecao()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prova", description="Prova9060 — benchmark de modelos locais")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(nome, f, *args, ajuda=""):
        sp = sub.add_parser(nome, help=ajuda)
        for arg in args:
            sp.add_argument(arg)
        sp.set_defaults(f=f)
        return sp

    add("perfil", cmd_perfil, "perfil", ajuda="exporta o perfil como variáveis de shell")
    add("vram", cmd_vram, ajuda="VRAM em uso (GiB)")
    add("servidor", cmd_servidor, ajuda="host e porta configurados (formato shell)")
    sp = add("registrar-carga", cmd_registrar_carga, "perfil", ajuda="usado pelo 01_subir_modelo")
    sp.add_argument("--segundos", type=float, default=None)
    sp.add_argument("--vram-base", default=None)
    for nome, f, aj in (("sanidade", cmd_sanidade, "smoke do servidor"),
                        ("desempenho", cmd_desempenho, "velocidade"),
                        ("contexto", cmd_contexto, "contexto longo"),
                        ("consistencia", cmd_consistencia, "estabilidade com temperatura"),
                        ("criticos", cmd_criticos, "repete casos críticos com várias seeds"),
                        ("pacote", cmd_pacote, "gera o pacote do juiz"),
                        ("pontuar", cmd_pontuar, "placar ENEM + relatório")):
        add(nome, f, "modelo", ajuda=aj)
    sp = add("suites", cmd_suites, "modelo", ajuda="roda as suítes da seleção")
    sp.add_argument("--so", default="", help="sobrescreve as suítes da seleção (vírgula)")
    sp.add_argument("--refazer", action="store_true")
    sp = add("agente", cmd_agente, "modelo", ajuda="cenários agênticos")
    sp.add_argument("--refazer", action="store_true")
    add("comparar", cmd_comparar, ajuda="tabela entre modelos")
    sp = add("estimar", cmd_estimar, ajuda="tempo estimado da rodada selecionada")
    sp.add_argument("perfil", nargs="?")
    sp.add_argument("--tps", type=float)
    add("validar", cmd_validar, ajuda="valida suítes e seleção")
    sp = add("proximo", cmd_proximo, ajuda="diz exatamente o próximo passo da série (comece por aqui)")
    sp.add_argument("--json", action="store_true", help="saída em JSON para máquina")
    sp = add("piloto", cmd_piloto, ajuda="executa sozinho os passos mecânicos até precisar do agente")
    sp.add_argument("--max-passos", type=int, default=200)
    sp = add("rodada", cmd_rodada, ajuda="mostra a seleção efetiva e as rodadas disponíveis")
    sp.add_argument("--nome", action="store_true", help="só o nome da rodada")
    sp = add("escolher", cmd_escolher, ajuda="escolhe a rodada (interativo ou direto)")
    sp.add_argument("rodada", nargs="?")
    sp.add_argument("--suites", default="", help="ex.: codigo,ferramentas")
    add("etapa-ativa", cmd_etapa_ativa, "etapa", ajuda="código de saída 0 se a etapa está na seleção")
    add("sandbox", cmd_sandbox, ajuda="diagnóstico do isolamento")
    sp = add("novo-perfil", cmd_novo_perfil, ajuda="cria config/modelos/<id>.toml a partir de GGUFs")
    sp.add_argument("gguf", nargs="+")
    sp.add_argument("--ctx", type=int, default=None)
    sp.add_argument("--forcar", action="store_true")
    a = ap.parse_args(argv)
    return a.f(a) or 0
