"""Contexto longo: fichas sintéticas (agulha no palheiro, multi-salto e agregação).

Os dados são gerados por seed, então nenhum modelo pode ter decorado as respostas.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

from .cliente import Cliente
from .verificadores import avaliar
from . import gpu

NOMES = ("Ana Bruno Carla Diego Elisa Fábio Gabriela Heitor Isabela João Karina Lucas Marta Nelson "
         "Olívia Paulo Quitéria Rafael Sabrina Tiago Úrsula Vinícius Wanda Xavier Yara Zeca Alice "
         "Bernardo Cecília Davi Estela Felipe Giovana Henrique Iara Júlio Lívia Murilo Natália Otávio "
         "Priscila Renato Simone Tomás Valéria Wagner Beatriz Caio Débora Enzo").split()
SOBRENOMES = ("Silva Souza Oliveira Pereira Lima Carvalho Ribeiro Almeida Costa Gomes Martins Araújo "
              "Barbosa Rocha Dias Teixeira Moreira Cardoso Nunes Mendes Freitas Vieira Campos Pinto "
              "Moura Castro Ramos Correia Fonseca Siqueira Tavares Batista Monteiro Prado Queiroz "
              "Duarte Macedo Rezende Pacheco Brandão Fagundes Guimarães Leal Paiva Sampaio").split()
SETORES = ["Almoxarifado", "Compras", "Jurídico", "Financeiro", "Manutenção", "Laboratório",
           "Expedição", "Recepção", "TI", "Qualidade"]
STATUS = ["ativo"] * 12 + ["pendente"] * 5 + ["arquivado"] * 4 + ["bloqueado"]
OBS = ["revisar inventário trimestral", "aguardando assinatura do gestor", "sem pendências",
       "solicitou troca de equipamento", "treinamento de segurança concluído", "atualizar cadastro",
       "férias programadas para o próximo mês", "acesso temporário ao arquivo morto",
       "remanejamento em análise", "documentação enviada ao RH", "auditoria interna agendada"]
PROJETOS = ["Aurora", "Basalto", "Cerrado", "Delta", "Esmeralda", "Farol", "Granito", "Horizonte"]


def gerar_fichas(rng: random.Random, n: int) -> list[dict]:
    pessoas = rng.sample([f"{a} {b}" for a in NOMES for b in SOBRENOMES], n)
    codigos = rng.sample(range(1000, 9999), n)
    fichas = []
    for i, nome in enumerate(pessoas):
        letras = "".join(rng.choice("BCDFGHJKLMNPQRSTVWXZ") for _ in range(2))
        fichas.append({"num": 100 + i, "nome": nome, "setor": rng.choice(SETORES),
                       "status": rng.choice(STATUS), "codigo": f"{letras}-{codigos[i]}",
                       "obs": rng.choice(OBS)})
    return fichas


def linha(f: dict) -> str:
    return (f"Ficha {f['num']:04d} | Responsável: {f['nome']} | Setor: {f['setor']} | "
            f"Status: {f['status']} | Código: {f['codigo']} | Obs.: {f['obs']}.")


def montar(linhas: list[str], cabecalho: str, pergunta: str) -> str:
    corpo = "\n".join(linhas)
    return (f"{cabecalho}\n\n<documento>\n{corpo}\n</documento>\n\n{pergunta}\n"
            "Responda somente com uma linha no formato: RESPOSTA: <valor>")


CAB = "Abaixo está o cadastro interno de fichas da empresa, com comunicados intercalados."


def _calibrar(cli: Cliente, rng: random.Random) -> float:
    amostra = "\n".join(linha(f) for f in gerar_fichas(rng, 40))
    return cli.contar_tokens(amostra) / 40


def gerar_casos(cli: Cliente, ctx: int, seed: int, reserva: int = 700) -> list[dict]:
    rng = random.Random(seed)
    tpl = _calibrar(cli, random.Random(seed + 1))  # tokens por linha
    # o palheiro é limitado a ctx - reserva, então o tamanho igual ao ctx também cabe
    tamanhos = [t for t in (4096, 8192, 16384, 32768) if t <= ctx]
    if not tamanhos:
        return []
    casos = []

    def fichas_para(alvo: int) -> list[dict]:
        # 0,95: margem para a variação de tokens por linha; reserva: pergunta + resposta (+ raciocínio)
        return gerar_fichas(rng, max(20, int(min(alvo, ctx - reserva) * 0.95 / tpl)))

    # 1) agulha simples em 3 posições por tamanho
    for t in tamanhos:
        fichas = fichas_para(t)
        dif = "facil" if t <= 8192 else "medio" if t <= 16384 else "dificil"
        for pos in (0.1, 0.5, 0.9):
            alvo = fichas[int(pos * (len(fichas) - 1))]
            casos.append({
                "id": f"contexto.busca-{t // 1024}k-{int(pos * 100)}", "dificuldade": dif, "tamanho": t,
                "prompt": montar([linha(f) for f in fichas], CAB,
                                 f"Qual é o código da ficha cujo responsável é {alvo['nome']}?"),
                "checks": [{"tipo": "resposta_final", "esperado": alvo["codigo"]}]})

    # 2) multi-salto: comunicado aponta a pessoa, a ficha dá o código
    for t, dif, com_atualizacao in ((tamanhos[min(1, len(tamanhos) - 1)], "medio", False),
                                    (tamanhos[-1], "dificil", True)):
        fichas = fichas_para(t)
        linhas = [linha(f) for f in fichas]
        projeto = rng.choice(PROJETOS)
        antigo, novo = rng.sample(fichas, 2)
        for p in rng.sample([x for x in PROJETOS if x != projeto], 4):  # distratores
            outro = rng.choice(fichas)
            linhas.insert(rng.randrange(len(linhas)),
                          f"COMUNICADO: o projeto {p} passa a ser coordenado por {outro['nome']}.")
        if com_atualizacao:
            linhas.insert(int(len(linhas) * 0.2),
                          f"COMUNICADO: o projeto {projeto} passa a ser coordenado por {antigo['nome']}.")
            linhas.insert(int(len(linhas) * 0.75),
                          f"COMUNICADO: a partir de hoje, {novo['nome']} substitui {antigo['nome']} "
                          f"na coordenação do projeto {projeto}.")
        else:
            linhas.insert(int(len(linhas) * 0.3),
                          f"COMUNICADO: o projeto {projeto} passa a ser coordenado por {novo['nome']}.")
        casos.append({
            "id": f"contexto.multisalto-{t // 1024}k" + ("-atualizado" if com_atualizacao else ""),
            "dificuldade": dif, "tamanho": t,
            "prompt": montar(linhas, CAB, f"Qual é o código da ficha da pessoa que coordena "
                                          f"atualmente o projeto {projeto}?"),
            "checks": [{"tipo": "resposta_final", "esperado": novo["codigo"]}]})

    # 3) agregação: contar fichas com setor + status
    fichas = fichas_para(tamanhos[0])
    setor = max(SETORES, key=lambda s: sum(f["setor"] == s and f["status"] == "pendente" for f in fichas))
    n = sum(f["setor"] == setor and f["status"] == "pendente" for f in fichas)
    casos.append({
        "id": f"contexto.contagem-{tamanhos[0] // 1024}k", "dificuldade": "dificil", "tamanho": tamanhos[0],
        "prompt": montar([linha(f) for f in fichas], CAB,
                         f"Quantas fichas do setor {setor} estão com status 'pendente'?"),
        "checks": [{"tipo": "resposta_final", "formato": "numero", "esperado": n}]})
    return casos


def rodar(cli: Cliente, ctx: int, seed: int, saida: Path, mult_tokens: float = 1.0,
          sel: dict | None = None) -> tuple[list[dict], float]:
    max_resp = int(96 * mult_tokens)
    reserva = 600 + max_resp + (cli.folga_pensamento if cli.pensamento else 0)
    casos = gerar_casos(cli, ctx, seed, reserva)
    if sel is not None:
        from .selecao import filtrar
        casos = filtrar(casos, sel)
    regs = []
    pico = gpu.vram_usada() or 0
    with saida.open("w", encoding="utf-8") as f:
        for c in casos:
            r = cli.chat([{"role": "user", "content": c["prompt"]}], max_resp, 0.0, seed,
                         extra={"cache_prompt": True})
            pico = max(pico, gpu.vram_usada() or 0)
            checks = avaliar(r, c)
            reg = {"id": c["id"], "suite": "contexto", "categoria": "contexto",
                   "dificuldade": c["dificuldade"], "critico": False, "avaliacao": "auto",
                   "tamanho_alvo": c["tamanho"], "erro_infra": bool(r.erro),
                   "q_auto": None if r.erro else (1.0 if checks[0]["ok"] else 0.0),
                   "checks": checks, "resposta": r.resumo(), "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
            f.flush()
            regs.append(reg)
            pp = f"{r.pp_tps:.0f}" if r.pp_tps else "-"
            marca = "INFRA" if r.erro else "OK" if checks[0]["ok"] else "ERRO"
            print(f"  {c['id']:<36} {marca:<5} prompt={r.tokens_prompt:>6} tok "
                  f"pp={pp:>5} tok/s {r.segundos:>5.1f}s  {checks[0]['detalhe'][:50]}", flush=True)
    return regs, pico
