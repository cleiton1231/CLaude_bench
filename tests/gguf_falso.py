"""Escreve GGUFs mínimos (só cabeçalho) para testar o gerador de perfis."""

import struct
from pathlib import Path


def _s(t: str) -> bytes:
    b = t.encode()
    return struct.pack("<Q", len(b)) + b


def _kv(chave: str, valor) -> bytes:
    out = _s(chave)
    if isinstance(valor, str):
        return out + struct.pack("<I", 8) + _s(valor)
    if isinstance(valor, bool):
        return out + struct.pack("<I", 7) + struct.pack("<?", valor)
    if isinstance(valor, int):
        return out + struct.pack("<I", 4) + struct.pack("<I", valor)
    if isinstance(valor, list) and all(isinstance(x, str) for x in valor):
        return out + struct.pack("<I", 9) + struct.pack("<IQ", 8, len(valor)) + b"".join(_s(x) for x in valor)
    if isinstance(valor, list):
        return out + struct.pack("<I", 9) + struct.pack("<IQ", 6, len(valor)) + struct.pack(f"<{len(valor)}f", *valor)
    raise TypeError(valor)


def escrever(caminho: Path, meta: dict, tamanho_bytes: int = 0) -> Path:
    corpo = b"GGUF" + struct.pack("<IQQ", 3, 0, len(meta)) + b"".join(_kv(k, v) for k, v in meta.items())
    with open(caminho, "wb") as f:
        f.write(corpo)
        if tamanho_bytes > len(corpo):
            f.truncate(tamanho_bytes)  # arquivo esparso: simula o tamanho dos pesos sem gastar disco
    return caminho


QWEN14 = {
    "general.architecture": "qwen3", "general.name": "Qwen3 14B",
    "qwen3.block_count": 40, "qwen3.attention.head_count": 40, "qwen3.attention.head_count_kv": 8,
    "qwen3.embedding_length": 5120, "qwen3.attention.key_length": 128, "qwen3.attention.value_length": 128,
    "qwen3.context_length": 40960,
    "tokenizer.ggml.tokens": ["a", "b", "c"], "tokenizer.ggml.scores": [0.1, 0.2, 0.3],
    "tokenizer.chat_template": "{% if enable_thinking %}<think>{% endif %}",
}
