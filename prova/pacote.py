"""Gera o pacote que o agente-juiz lê (pacote_juiz.md) e o modelo de notas (notas_juiz.modelo.json)."""

from __future__ import annotations

import json
from pathlib import Path

from .pontuacao import carregar_registros, carregar_notas
from .suites import todas


def _corta(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n… [+{len(s) - n} caracteres cortados]"


def _transcricao(reg: dict) -> str:
    msgs = reg.get("transcricao", [])
    if msgs and msgs[0]["role"] == "system":
        msgs = msgs[1:]
    partes = []
    for m in msgs:
        if m["role"] == "user":
            partes.append(f"**Usuário:** {_corta(m['content'], 1500)}")
        elif m["role"] == "assistant":
            txt = f"**Modelo:** {_corta(m.get('content') or '', 3500)}"
            if m.get("tool_calls"):
                txt += f"\n`tool_calls`: {json.dumps(m['tool_calls'], ensure_ascii=False)[:600]}"
            partes.append(txt)
        elif m["role"] == "tool":
            partes.append(f"**Ferramenta:** {_corta(m['content'], 600)}")
    return "\n\n".join(partes)


def gerar(d: Path) -> tuple[Path, int]:
    casos = {c["id"]: c for s in todas() for c in s["casos"]}
    regs = carregar_registros(d)
    notas = carregar_notas(d)
    juiz = [r for r in regs if r["avaliacao"] == "juiz"]
    L = [f"# Pacote do juiz — {d.name}", "",
         "Leia `JULGAMENTO.md` antes. Dê nota 0–3 a cada caso abaixo e grave em `notas_juiz.json` "
         "(copie `notas_juiz.modelo.json`). Casos automáticos NÃO são reavaliados. "
         "Depois rode `scripts/09_pontuar.sh`, leia `relatorio.md` e escreva `parecer.md` (JULGAMENTO.md §8).", "",
         f"Casos para julgar: **{len(juiz)}** · já julgados: {sum(1 for r in juiz if r['id'] in notas)}", ""]
    for r in juiz:
        c = casos.get(r["id"], {})
        L += ["---", "", f"## {r['id']}",
              f"`dificuldade={r['dificuldade']}` `critico={str(r['critico']).lower()}` "
              f"`tokens={r['resposta']['tokens_saida']}` `fim={r['resposta'].get('fim', '')}`", ""]
        if c.get("sistema"):
            L += [f"**Sistema:** {_corta(c['sistema'], 800)}", ""]
        L += ["### Gabarito", c.get("gabarito", "").strip(), ""]
        if c.get("deve_cobrir"):
            L.append("**Deve cobrir:** " + "; ".join(c["deve_cobrir"]))
        if c.get("nao_pode"):
            L.append("**Não pode:** " + "; ".join(c["nao_pode"]))
        if r["checks"]:
            L += ["", "**Sinais automáticos (pistas, não nota):** " +
                  "; ".join(f"{'✔' if x['ok'] else '✘'} {x['tipo']}: {x['detalhe'][:90]}" for x in r["checks"])]
        L += ["", "### Conversa", _transcricao(r), ""]

    falhas_faceis = [r for r in regs if r["avaliacao"] == "auto" and r["dificuldade"] == "facil"
                     and (r.get("q_auto") or 0) < 1]
    if falhas_faceis:
        L += ["---", "", "## Para conferência: erros automáticos em casos FÁCEIS", "",
              "Não mude a nota. Se o erro parecer bug do verificador (ex.: resposta certa mas fora do "
              "formato pedido por culpa do enunciado), registre em `suspeitas_verificador`.", ""]
        for r in falhas_faceis:
            det = "; ".join(x["detalhe"][:120] for x in r["checks"] if not x["ok"])
            L += [f"### {r['id']}", f"Falhas: {det}", "", "```", _corta(r["resposta"].get("texto", ""), 1200), "```", ""]

    out = d / "pacote_juiz.md"
    out.write_text("\n".join(L), encoding="utf-8")
    modelo = {"juiz": "<nome do agente>",
              "casos": {r["id"]: notas.get(r["id"], {"nota": None, "motivo": ""}) for r in juiz},
              "suspeitas_verificador": []}
    (d / "notas_juiz.modelo.json").write_text(json.dumps(modelo, indent=2, ensure_ascii=False), encoding="utf-8")
    return out, len(juiz)
