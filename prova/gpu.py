"""Leitura de VRAM/temperatura/consumo da GPU AMD via sysfs (amdgpu). Sem dependências."""

from __future__ import annotations

import glob
import os
from pathlib import Path

from .config import hardware


def card() -> Path | None:
    forcado = hardware().get("gpu", {}).get("sysfs") or os.environ.get("PROVA_GPU_SYSFS")
    if forcado:
        p = Path(forcado)
        return p if p.exists() else None
    # escolhe a AMD com mais VRAM: em Ryzen com iGPU, card0 costuma ser a integrada
    candidatos = []
    for dev in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        try:
            if Path(dev, "vendor").read_text().strip() == "0x1002":
                candidatos.append((int(Path(dev, "mem_info_vram_total").read_text()), Path(dev)))
        except (OSError, ValueError):
            continue
    return max(candidatos)[1] if candidatos else None


def _ler(p: Path) -> str | None:
    try:
        return p.read_text().strip()
    except OSError:
        return None


def leitura() -> dict:
    c = card()
    if not c:
        return {}
    out: dict = {}
    for chave, arq in (("vram_usada_gib", "mem_info_vram_used"), ("vram_total_gib", "mem_info_vram_total"),
                       ("gtt_usada_gib", "mem_info_gtt_used")):
        v = _ler(c / arq)
        if v and v.isdigit():
            out[chave] = round(int(v) / 2**30, 2)
    v = _ler(c / "gpu_busy_percent")
    if v and v.isdigit():
        out["ocupacao_pct"] = int(v)
    for hw in glob.glob(str(c / "hwmon" / "hwmon*")):
        h = Path(hw)
        for arq in ("temp1_input", "temp2_input", "temp3_input"):
            label = _ler(h / arq.replace("input", "label")) or arq
            val = _ler(h / arq)
            if val and val.lstrip("-").isdigit():
                out[f"temp_{label}_c"] = int(val) / 1000
        pw = _ler(h / "power1_average") or _ler(h / "power1_input")
        if pw and pw.isdigit():
            out["potencia_w"] = round(int(pw) / 1e6, 1)
    return out


def vram_usada() -> float | None:
    return leitura().get("vram_usada_gib")
