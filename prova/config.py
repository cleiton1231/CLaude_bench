"""Leitura de configuração e caminhos de resultado.

Camadas (a de baixo sobrescreve a de cima):
  config/hardware.toml  padrões do projeto (versionado)
  config/local.toml     sua máquina: caminho do llama-server, porta, sandbox (fora do git)
  variáveis PROVA_*     ajustes pontuais por execução
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
SUITES = RAIZ / "suites"
RESULTADOS = Path(os.environ.get("PROVA_RESULTADOS", RAIZ / "resultados"))
MODELOS = Path(os.environ.get("PROVA_DIR_MODELOS", RAIZ / "config" / "modelos"))

PESOS_PADRAO = {
    "codigo": 20, "raciocinio": 15, "instrucoes": 12, "ferramentas": 13,
    "agente": 10, "ceticismo": 12, "redacao": 8, "contexto": 10,
}


def ler_toml(caminho: Path | str) -> dict[str, Any]:
    with open(caminho, "rb") as f:
        return tomllib.load(f)


def mesclar(base: dict, extra: dict) -> dict:
    """Mescla dicionários recursivamente; `extra` vence."""
    out = dict(base)
    for k, v in extra.items():
        out[k] = mesclar(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def hardware() -> dict[str, Any]:
    cfg = ler_toml(RAIZ / "config" / "hardware.toml")
    local = Path(os.environ.get("PROVA_CONFIG_LOCAL", RAIZ / "config" / "local.toml"))
    if local.exists():
        cfg = mesclar(cfg, ler_toml(local))
    srv = cfg.setdefault("servidor", {})
    if "PROVA_BIN" in os.environ:
        srv["binario"] = os.environ["PROVA_BIN"]
    srv["host"] = os.environ.get("PROVA_HOST", srv.get("host", "127.0.0.1"))
    srv["porta"] = int(os.environ.get("PROVA_PORTA", srv.get("porta", 8080)))
    cfg.setdefault("bench", {})
    if "PROVA_SEED" in os.environ:
        cfg["bench"]["seed"] = int(os.environ["PROVA_SEED"])
    cfg["bench"].setdefault("seed", 1234)
    cfg.setdefault("pesos", PESOS_PADRAO)
    sb = cfg.setdefault("sandbox", {})
    sb["modo"] = os.environ.get("PROVA_SANDBOX", sb.get("modo", "auto"))
    sb.setdefault("exigir_isolamento", False)
    sb.setdefault("memoria_mb", 1024)
    sb.setdefault("cpu_s", 20)
    return cfg


def endpoint() -> str:
    srv = hardware()["servidor"]
    return f"http://{srv['host']}:{srv['porta']}"


def perfil(caminho: Path | str) -> dict[str, Any]:
    p = Path(caminho)
    if not p.exists():
        p = MODELOS / f"{caminho}.toml"
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
