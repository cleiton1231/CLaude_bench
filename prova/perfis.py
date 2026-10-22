"""Cria perfis de modelo a partir do arquivo GGUF (lê o cabeçalho; não carrega pesos).

Estima o maior contexto que cabe na VRAM: pesos (tamanho do arquivo) + KV cache
(2 × camadas × cabeças_kv × dim_cabeça × bytes por elemento × tokens) + margem para buffers.
Modelos híbridos (atenção linear/SSM) gastam menos KV que isso: a estimativa é conservadora.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any, BinaryIO

from .config import MODELOS, hardware

BYTES_KV = {"f16": 2.0, "q8_0": 1.0625, "q4_0": 0.5625}
MARGEM_GIB = 1.2  # buffers de computação, contexto do driver, compositor
CTXS = (32768, 16384, 8192, 4096)

_FMT = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


class GGUFInvalido(ValueError):
    pass


def _ler(f: BinaryIO, fmt: str):
    n = struct.calcsize(fmt)
    b = f.read(n)
    if len(b) != n:
        raise GGUFInvalido("arquivo truncado")
    return struct.unpack(fmt, b)[0]


def _str(f: BinaryIO) -> str:
    n = _ler(f, "<Q")
    if n > 1 << 24:
        raise GGUFInvalido("string absurda no cabeçalho")
    return f.read(n).decode("utf-8", "replace")


def _valor(f: BinaryIO, tipo: int, guardar: bool = True) -> Any:
    if tipo == 8:
        return _str(f)
    if tipo == 9:
        sub, n = _ler(f, "<I"), _ler(f, "<Q")
        if sub in _FMT and not guardar:  # array numérico grande (ex.: scores do tokenizer): pula
            f.seek(n * struct.calcsize(_FMT[sub]), 1)
            return None
        itens = [_valor(f, sub, guardar) for _ in range(n)]
        return itens if guardar else None
    if tipo in _FMT:
        return _ler(f, _FMT[tipo])
    raise GGUFInvalido(f"tipo de metadado desconhecido {tipo}")


def ler_metadados(caminho: Path) -> dict[str, Any]:
    with open(caminho, "rb") as f:
        if f.read(4) != b"GGUF":
            raise GGUFInvalido(f"{caminho.name} não é GGUF")
        versao = _ler(f, "<I")
        if versao < 2:
            raise GGUFInvalido(f"GGUF v{versao} não suportado")
        _ler(f, "<Q")  # tensores
        n_kv = _ler(f, "<Q")
        meta: dict[str, Any] = {}
        for _ in range(n_kv):
            chave = _str(f)
            tipo = _ler(f, "<I")
            # tokenizer.* tem arrays enormes; só o chat_template interessa
            guardar = not chave.startswith("tokenizer.") or chave == "tokenizer.chat_template"
            v = _valor(f, tipo, guardar)
            if guardar:
                meta[chave] = v
    return meta


def kv_bytes_por_token(meta: dict, kv: str = "q8_0") -> float | None:
    arch = meta.get("general.architecture")
    if not arch:
        return None
    camadas = meta.get(f"{arch}.block_count")
    cab_kv = meta.get(f"{arch}.attention.head_count_kv", meta.get(f"{arch}.attention.head_count"))
    cab = meta.get(f"{arch}.attention.head_count")
    emb = meta.get(f"{arch}.embedding_length")
    k = meta.get(f"{arch}.attention.key_length")
    v = meta.get(f"{arch}.attention.value_length")
    if isinstance(cab, list):
        cab = max(cab) or None
    if k is None and emb and cab:
        k = v = emb // cab
    v = v or k
    if not (camadas and cab_kv and k):
        return None
    soma_cab = sum(cab_kv) if isinstance(cab_kv, list) else cab_kv * camadas
    return soma_cab * (k + v) * BYTES_KV.get(kv, 2.0)


def sugerir_ctx(tamanho_gib: float, kv_por_token: float | None, ctx_max: int | None,
                vram_gib: float) -> tuple[int, list[str]]:
    avisos = []
    livre = vram_gib - MARGEM_GIB - tamanho_gib
    if livre <= 0.5:
        avisos.append(f"pesos ({tamanho_gib:.1f} GiB) não cabem com folga em {vram_gib:g} GiB: "
                      "use quant menor ou --n-cpu-moe (MoE) em args_extra")
        return 4096, avisos
    if kv_por_token is None:
        avisos.append("não consegui ler a geometria de atenção no GGUF; ctx sugerido por tamanho do arquivo")
        ctx = 32768 if livre > 6 else 16384 if livre > 3 else 8192
    else:
        ctx = next((c for c in CTXS if c * kv_por_token / 2**30 <= livre), 4096)
    if ctx_max and ctx > ctx_max:
        ctx = max(c for c in (*CTXS, 2048) if c <= ctx_max)
    return ctx, avisos


def _id(nome_arquivo: str) -> str:
    base = re.sub(r"\.gguf$", "", nome_arquivo, flags=re.I)
    base = re.sub(r"-0000\d-of-0000\d$", "", base)
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")


def _quant(nome: str) -> str:
    m = re.search(r"(UD-)?(I?Q\d_[A-Z0-9_]+|PQ\d_\d|Q\d_\d|BF16|F16|F32|MXFP4)", nome, re.I)
    return m.group(0).upper() if m else "?"


def gravar_perfil(gguf: Path, ctx: int | None = None, forcar: bool = False,
                  destino: Path | None = None) -> tuple[Path | None, list[str]]:
    if not gguf.exists():
        raise FileNotFoundError(gguf)
    destino = destino or MODELOS
    arq = destino / f"{_id(gguf.name)}.toml"
    if arq.exists() and not forcar:
        return None, ["perfil já existe (use --forcar para sobrescrever)"]
    avisos: list[str] = []
    try:
        meta = ler_metadados(gguf)
    except (GGUFInvalido, OSError) as e:
        meta = {}
        avisos.append(f"cabeçalho GGUF ilegível ({e}); perfil com valores padrão")
    arch = meta.get("general.architecture", "?")
    tamanho = gguf.stat().st_size / 2**30
    if re.search(r"-0000\d-of-0000(\d)", gguf.name):
        avisos.append("GGUF dividido em partes: o tamanho considera só a primeira; confira a VRAM no 01")
    vram = float(hardware().get("gpu", {}).get("vram_gib", 16))
    ctx_max = meta.get(f"{arch}.context_length")
    kvt = kv_bytes_por_token(meta)
    ctx_sug, av = sugerir_ctx(tamanho, kvt, ctx_max, vram)
    avisos += av
    moe = bool(meta.get(f"{arch}.expert_count"))
    template = meta.get("tokenizer.chat_template") or ""
    pensa = "<think>" in template or "enable_thinking" in template
    nome = meta.get("general.name") or gguf.stem
    linhas = [
        "# Gerado por `python3 -m prova novo-perfil`. Revise antes de rodar.",
        f'nome = "{nome} {_quant(gguf.name)}"',
        f'gguf = "{gguf.resolve()}"',
        f'familia = "{arch}"',
        f'quant = "{_quant(gguf.name)}"',
        f"tamanho_gib = {tamanho:.2f}",
        "",
        f"ctx = {ctx or ctx_sug}" + ("" if ctx else f"  # estimado: pesos {tamanho:.1f} GiB + KV q8_0"
                                     + (f" {kvt * ctx_sug / 2**30:.1f} GiB" if kvt else "")
                                     + (f" · máximo do modelo {ctx_max}" if ctx_max else "")),
        "ngl = 99",
        'kv_cache = "q8_0"',
        "flash_attn = true",
        "pensamento = false" + ("  # o template suporta raciocínio; true = rodada bem mais longa" if pensa else ""),
        "args_extra = []" + ("  # MoE: se não couber, use [\"--n-cpu-moe\", \"8\"]" if moe else ""),
    ]
    destino.mkdir(parents=True, exist_ok=True)
    arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return arq, avisos
