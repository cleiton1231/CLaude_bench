"""CLI: python3 -m prova <comando>. Os scripts em scripts/ chamam estes comandos."""

from __future__ import annotations

import argparse
import json
import os
import shlex
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
    etapas[nome] = {"fim": time.strftime("%Y-%m-%dT%H:%M:%S"), "minutos": round((time.monotonic() - t0) / 60, 2), **extra}
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
                       seed=config.hardware()["bench"]["seed"], etapas={})
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
    if not rt.chamadas:
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
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    res = medir(cli, perf["ctx"], config.hardware()["bench"]["seed"])
    (config.dir_modelo(a.modelo) / "desempenho.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    _etapa(a.modelo, "desempenho", t0)
    return 0


def cmd_suites(a) -> int:
    from .executor import rodar_suite
    from .suites import todas
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    seed = config.hardware()["bench"]["seed"]
    nomes = a.so.split(",") if a.so else None
    suites = todas(nomes)
    if not suites:
        sys.exit(f"nenhuma suíte encontrada para {nomes}")
    d = config.dir_modelo(a.modelo) / "suites"
    for s in suites:
        print(f"\n## suíte {s['suite']} v{s['versao']} ({len(s['casos'])} casos)")
        rodar_suite(cli, s, d / f"{s['suite']}.jsonl", seed, perf["mult_tokens"], a.refazer)
    _etapa(a.modelo, "suites" + (f":{a.so}" if a.so else ""), t0)
    return 0


def cmd_agente(a) -> int:
    from .agente import rodar_todos
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    rodar_todos(cli, config.dir_modelo(a.modelo) / "agente.jsonl", config.hardware()["bench"]["seed"],
                perf["mult_tokens"], a.refazer)
    _etapa(a.modelo, "agente", t0)
    return 0


def cmd_contexto(a) -> int:
    from .contexto import rodar
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    _, pico = rodar(cli, perf["ctx"], config.hardware()["bench"]["seed"],
                    config.dir_modelo(a.modelo) / "contexto.jsonl", perf["mult_tokens"])
    _etapa(a.modelo, "contexto", t0, vram_pico_gib=pico)
    return 0


def cmd_consistencia(a) -> int:
    from .consistencia import rodar
    t0 = time.monotonic()
    cli, perf = _cliente(a.modelo)
    res = rodar(cli, config.dir_modelo(a.modelo), config.hardware()["bench"]["seed"], perf["mult_tokens"])
    print(f"estáveis: {res['taxa_estavel'] * 100:.0f}%")
    _etapa(a.modelo, "consistencia", t0)
    return 0


def cmd_pacote(a) -> int:
    from .pacote import gerar
    out, n = gerar(config.dir_modelo(a.modelo))
    print(f"pacote: {out} ({n} casos para julgar)")
    print(f"modelo de notas: {out.parent / 'notas_juiz.modelo.json'}")
    return 0


def cmd_pontuar(a) -> int:
    from .pontuacao import calcular, relatorio_md
    d = config.dir_modelo(a.modelo)
    p = calcular(d)
    (d / "placar.json").write_text(json.dumps(p, indent=2, ensure_ascii=False))
    (d / "relatorio.md").write_text(relatorio_md(p), encoding="utf-8")
    print(f"nota geral {p['nota_geral']} ({p['faixa_geral']}) — {'completo' if p['completo'] else 'INCOMPLETO'}")
    for nome, c in sorted(p["categorias"].items()):
        print(f"  {nome:<12} {c['nota']:>5}  {c['faixa']:<11} n={c['n']}" + ("  [incoerente]" if c["incoerente"] else ""))
    if p["pendentes_juiz"]:
        print(f"  pendentes de juiz: {len(p['pendentes_juiz'])}")
    if p["criticos_falhos"]:
        print(f"  CRÍTICOS FALHOS: {', '.join(p['criticos_falhos'])}")
    print(f"relatório: {d / 'relatorio.md'}")
    return 0


def cmd_comparar(a) -> int:
    from .pontuacao import comparativo_md
    placares = [json.loads(p.read_text()) for p in sorted(config.RESULTADOS.glob("*/placar.json"))]
    if not placares:
        sys.exit("nenhum placar.json encontrado; rode 09_pontuar.sh antes")
    out = config.RESULTADOS / "comparativo.md"
    out.write_text(comparativo_md(placares), encoding="utf-8")
    print(out.read_text())
    return 0


def cmd_estimar(a) -> int:
    from .agente import carregar_cenarios
    from .suites import todas
    perf = config.perfil(a.perfil) if a.perfil else {"mult_tokens": 1.0, "folga_pensamento": 0}
    mult, folga = perf["mult_tokens"], perf["folga_pensamento"]
    tps = a.tps or config.hardware()["bench"].get("tok_s_referencia", 30)
    teto = 0
    print(f"{'suíte':<14}{'casos':>6}{'teto tok':>10}")
    for s in todas():
        t = sum(c["max_tokens"] * (1 + len(c.get("turnos_seguintes", [])) + (1 if c.get("ferramentas") else 0))
                for c in s["casos"])
        t = t * mult + folga * len(s["casos"])
        teto += t
        print(f"{s['suite']:<14}{len(s['casos']):>6}{int(t):>10}")
    cen = carregar_cenarios()
    t_ag = sum(c["max_tokens"] * c["max_turnos"] for c in cen) / 3 * mult  # turno médio usa ~1/3 do teto
    print(f"{'agente':<14}{len(cen):>6}{int(t_ag):>10}  (estimado)")
    teto += t_ag
    tipico = teto * 0.45  # respostas costumam usar menos da metade do teto
    extras_min = 3 + 5 + 4  # desempenho + contexto (prefill) + consistência, aproximado
    print(f"\nteto de geração: {int(teto)} tok = {teto / tps / 60:.0f} min a {tps} tok/s")
    print(f"típico: ~{int(tipico)} tok = {tipico / tps / 60:.0f} min + ~{extras_min} min de desempenho/contexto/"
          f"consistência ≈ {tipico / tps / 60 + extras_min:.0f} min por modelo")
    return 0


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
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prova")
    sub = ap.add_subparsers(dest="cmd", required=True)
    def add(nome, f, *args):
        sp = sub.add_parser(nome)
        for arg in args:
            sp.add_argument(arg)
        sp.set_defaults(f=f)
        return sp
    add("perfil", cmd_perfil, "perfil")
    add("vram", cmd_vram)
    sp = add("registrar-carga", cmd_registrar_carga, "perfil")
    sp.add_argument("--segundos", type=float, default=None)
    sp.add_argument("--vram-base", default=None)
    for nome, f in (("sanidade", cmd_sanidade), ("desempenho", cmd_desempenho), ("contexto", cmd_contexto),
                    ("consistencia", cmd_consistencia), ("pacote", cmd_pacote), ("pontuar", cmd_pontuar)):
        add(nome, f, "modelo")
    sp = add("suites", cmd_suites, "modelo")
    sp.add_argument("--so", default="", help="lista de suítes separadas por vírgula")
    sp.add_argument("--refazer", action="store_true")
    sp = add("agente", cmd_agente, "modelo")
    sp.add_argument("--refazer", action="store_true")
    add("comparar", cmd_comparar)
    sp = add("estimar", cmd_estimar)
    sp.add_argument("perfil", nargs="?")
    sp.add_argument("--tps", type=float)
    add("validar", cmd_validar)
    a = ap.parse_args(argv)
    return a.f(a) or 0
