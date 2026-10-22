"""Leitura de configuração (hardware + perfil de modelo) e caminhos de resultado."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
SUITES = RAIZ / "suites"
RESULTADOS = RAIZ / "resultados"

PESOS_PADRAO = {
    "codigo": 20, "raciocinio": 15, "instrucoes": 12, "ferramentas": 13,
    "agente": 10, "ceticismo": 12, "redacao": 8, "contexto": 10,
}


def ler_toml(caminho: Path | str) -> dict[str, Any]:
    with open(caminho, "rb") as f:
        return tomllib.load(f)


def hardware() -> dict[str, Any]:
    cfg = ler_toml(RAIZ / "config" / "hardware.toml")
    srv = cfg.setdefault("servidor", {})
    srv["host"] = os.environ.get("PROVA_HOST", srv.get("host", "127.0.0.1"))
    srv["porta"] = int(os.environ.get("PROVA_PORTA", srv.get("porta", 8080)))
    cfg.setdefault("bench", {})
    if "PROVA_SEED" in os.environ:
        cfg["bench"]["seed"] = int(os.environ["PROVA_SEED"])
    cfg["bench"].setdefault("seed", 1234)
    cfg.setdefault("pesos", PESOS_PADRAO)
    return cfg


def endpoint() -> str:
    srv = hardware()["servidor"]
    return f"http://{srv['host']}:{srv['porta']}"


def perfil(caminho: Path | str) -> dict[str, Any]:
    p = Path(caminho)
    if not p.exists():
        p = RAIZ / "config" / "modelos" / f"{caminho}.toml"
    dados = ler_toml(p)
    dados["id"] = p.stem
    dados["arquivo"] = str(p)
    dados.setdefault("nome", p.stem)
    dados.setdefault("ctx", 16384)
    dados.setdefault("ngl", 99)
    dados.setdefault("kv_cache", "q8_0")
    dados.setdefault("flash_attn", True)
    dados.setdefault("pensamento", False)
    dados.setdefault("args_extra", [])
    # modelos com raciocínio: teto da resposta x mult_tokens + folga fixa por chamada para pensar
    dados.setdefault("mult_tokens", 1.5 if dados["pensamento"] else 1.0)
    dados.setdefault("folga_pensamento", 2048 if dados["pensamento"] else 0)
    return dados


def dir_modelo(modelo_id: str) -> Path:
    d = RESULTADOS / modelo_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def meta(modelo_id: str) -> dict[str, Any]:
    arq = dir_modelo(modelo_id) / "meta.json"
    return json.loads(arq.read_text()) if arq.exists() else {}


def salvar_meta(modelo_id: str, **campos: Any) -> dict[str, Any]:
    m = meta(modelo_id)
    m.update(campos)
    (dir_modelo(modelo_id) / "meta.json").write_text(json.dumps(m, indent=2, ensure_ascii=False))
    return m


def perfil_do_resultado(modelo_id: str) -> dict[str, Any]:
    """Perfil gravado no meta.json pelo 01_subir_modelo (fonte de verdade da rodada)."""
    m = meta(modelo_id)
    if "perfil" in m:
        return m["perfil"]
    return perfil(modelo_id)
