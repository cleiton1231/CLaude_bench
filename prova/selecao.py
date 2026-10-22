"""Seleção do que rodar: rodada (preset) + ajustes do usuário.

Ordem de precedência:
  1. PROVA_RODADA=<nome>       usa o preset config/rodadas/<nome>.toml como está
  2. config/selecao.toml       `rodada = "<nome>"` + qualquer campo abaixo para sobrescrever
  3. padrão                    rodada "completa"
Ajustes rápidos por ambiente: PROVA_SUITES=codigo,raciocinio · PROVA_ETAPAS=suites,agente

Campos: etapas, suites, dificuldades, incluir, excluir (globs de id de caso), repeticoes_criticos,
repeticoes_criticos_agente.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from .config import RAIZ, ler_toml

ETAPAS = ("desempenho", "suites", "agente", "contexto", "consistencia", "criticos")
DIR_RODADAS = RAIZ / "config" / "rodadas"
ARQ_SELECAO = RAIZ / "config" / "selecao.toml"
CAMPOS = ("etapas", "suites", "dificuldades", "incluir", "excluir", "repeticoes_criticos",
          "repeticoes_criticos_agente")


class SelecaoInvalida(ValueError):
    pass


def rodadas() -> dict[str, dict]:
    return {p.stem: ler_toml(p) for p in sorted(DIR_RODADAS.glob("*.toml"))}


def _lista(v: Any, todas: tuple[str, ...] | list[str]) -> list[str]:
    if v in (None, "todas", "todos", ["todas"], ["todos"]):
        return list(todas)
    if isinstance(v, str):
        v = [x.strip() for x in v.split(",") if x.strip()]
    return list(v)


def carregar() -> dict[str, Any]:
    from .suites import nomes_suites
    arq = Path(os.environ.get("PROVA_SELECAO", ARQ_SELECAO))
    ajustes: dict = {}
    if os.environ.get("PROVA_RODADA"):
        nome = os.environ["PROVA_RODADA"]
    elif arq.exists():
        ajustes = ler_toml(arq)
        nome = ajustes.get("rodada", "completa")
    else:
        nome = "completa"
    presets = rodadas()
    if nome not in presets:
        raise SelecaoInvalida(f"rodada '{nome}' não existe (há: {', '.join(presets)})")
    sel = {**presets[nome], **{k: v for k, v in ajustes.items() if k in CAMPOS}}
    if os.environ.get("PROVA_SUITES"):
        sel["suites"] = os.environ["PROVA_SUITES"]
    if os.environ.get("PROVA_ETAPAS"):
        sel["etapas"] = os.environ["PROVA_ETAPAS"]

    sel["nome"] = nome + (" (ajustada)" if any(k in ajustes for k in CAMPOS) else "")
    sel["etapas"] = _lista(sel.get("etapas"), ETAPAS)
    sel["suites"] = _lista(sel.get("suites"), nomes_suites())
    sel["dificuldades"] = _lista(sel.get("dificuldades"), ("facil", "medio", "dificil"))
    sel["incluir"] = list(sel.get("incluir", []))
    sel["excluir"] = list(sel.get("excluir", []))
    sel["repeticoes_criticos"] = int(sel.get("repeticoes_criticos", 4))
    sel["repeticoes_criticos_agente"] = int(sel.get("repeticoes_criticos_agente", 2))
    for e in sel["etapas"]:
        if e not in ETAPAS:
            raise SelecaoInvalida(f"etapa desconhecida '{e}' (válidas: {', '.join(ETAPAS)})")
    for s in sel["suites"]:
        if s not in nomes_suites():
            raise SelecaoInvalida(f"suíte desconhecida '{s}' (válidas: {', '.join(nomes_suites())})")
    for d in sel["dificuldades"]:
        if d not in ("facil", "medio", "dificil"):
            raise SelecaoInvalida(f"dificuldade inválida '{d}'")
    return sel


def ativa(etapa: str, sel: dict | None = None) -> bool:
    return etapa in (sel or carregar())["etapas"]


def aceita(caso: dict, sel: dict) -> bool:
    cid = caso["id"]
    if caso.get("dificuldade") not in sel["dificuldades"]:
        return False
    if sel["incluir"] and not any(fnmatch.fnmatch(cid, g) for g in sel["incluir"]):
        return False
    return not any(fnmatch.fnmatch(cid, g) for g in sel["excluir"])


def filtrar(casos: list[dict], sel: dict) -> list[dict]:
    return [c for c in casos if aceita(c, sel)]


def categorias_esperadas(sel: dict) -> list[str]:
    """Categorias que a rodada deve produzir (para saber se o placar está completo)."""
    from .agente import carregar_cenarios
    from .suites import todas
    cats = []
    if "suites" in sel["etapas"]:
        cats += [s["categoria"] for s in todas(sel["suites"]) if filtrar(s["casos"], sel)]
    if "agente" in sel["etapas"] and filtrar(carregar_cenarios(), sel):
        cats.append("agente")
    if "contexto" in sel["etapas"]:
        cats.append("contexto")
    return cats


def resumo(sel: dict) -> dict:
    return {k: sel[k] for k in ("nome", *CAMPOS)}


def gravar(nome: str, ajustes: dict | None = None, arq: Path | None = None) -> Path:
    """Grava config/selecao.toml (formato simples, escrito à mão para não depender de bibliotecas)."""
    def fmt(v):
        if isinstance(v, list):
            return "[" + ", ".join(f'"{x}"' for x in v) + "]"
        return str(v) if isinstance(v, int) else f'"{v}"'
    linhas = ["# Gerado por `python3 -m prova escolher`. Pode editar à mão.",
              "# Campos possíveis: " + ", ".join(CAMPOS), f'rodada = "{nome}"']
    for k, v in (ajustes or {}).items():
        if k in CAMPOS:
            linhas.append(f"{k} = {fmt(v)}")
    arq = arq or Path(os.environ.get("PROVA_SELECAO", ARQ_SELECAO))
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return arq
