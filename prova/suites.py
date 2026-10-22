"""Carrega as suítes TOML e valida o formato dos casos."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import SUITES, ler_toml
from .ferramentas import CATALOGO
from .verificadores import CHECKS

DIFICULDADES = ("facil", "medio", "dificil")


class SuiteInvalida(Exception):
    pass


def _validar(caso: dict, arq: str) -> None:
    cid = caso.get("id", "?")
    for campo in ("id", "dificuldade", "prompt"):
        if campo not in caso:
            raise SuiteInvalida(f"{arq}:{cid}: campo obrigatório '{campo}' ausente")
    if caso["dificuldade"] not in DIFICULDADES:
        raise SuiteInvalida(f"{arq}:{cid}: dificuldade inválida {caso['dificuldade']!r}")
    if caso["avaliacao"] not in ("auto", "juiz"):
        raise SuiteInvalida(f"{arq}:{cid}: avaliacao deve ser auto|juiz")
    if caso["avaliacao"] == "auto" and not caso.get("checks"):
        raise SuiteInvalida(f"{arq}:{cid}: caso auto sem checks")
    if caso["avaliacao"] == "juiz" and not caso.get("gabarito"):
        raise SuiteInvalida(f"{arq}:{cid}: caso de juiz sem gabarito")
    for chk in caso.get("checks", []):
        if chk.get("tipo") not in CHECKS:
            raise SuiteInvalida(f"{arq}:{cid}: check desconhecido {chk.get('tipo')!r}")
    for f in caso.get("ferramentas", []):
        if f not in CATALOGO:
            raise SuiteInvalida(f"{arq}:{cid}: ferramenta desconhecida {f!r}")


def carregar(arquivo: Path) -> dict[str, Any]:
    dados = ler_toml(arquivo)
    padrao = dados.get("padrao", {})
    casos = []
    for bruto in dados.get("caso", []):
        caso = {**padrao, **bruto}
        caso.setdefault("avaliacao", "auto")
        caso.setdefault("critico", False)
        caso.setdefault("consistencia", False)
        caso.setdefault("max_tokens", 512)
        caso["suite"] = dados["suite"]
        caso["categoria"] = dados["categoria"]
        _validar(caso, arquivo.name)
        casos.append(caso)
    ids = [c["id"] for c in casos]
    if len(ids) != len(set(ids)):
        raise SuiteInvalida(f"{arquivo.name}: ids duplicados")
    return {"suite": dados["suite"], "categoria": dados["categoria"],
            "versao": dados.get("versao", 1), "arquivo": arquivo.name, "casos": casos}


def todas(nomes: list[str] | None = None) -> list[dict[str, Any]]:
    """Todas as suítes, ou só as de `nomes` (lista vazia = nenhuma)."""
    suites = [carregar(p) for p in sorted(SUITES.glob("*.toml"))]
    if nomes is not None:
        suites = [s for s in suites if s["suite"] in nomes]
    return suites


def nomes_suites() -> list[str]:
    return [ler_toml(p)["suite"] for p in sorted(SUITES.glob("*.toml"))]
