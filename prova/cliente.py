"""Cliente HTTP mínimo para o llama-server (API OpenAI-compatível). Só stdlib."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

RE_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


class ErroCliente(Exception):
    pass


@dataclass
class Resposta:
    texto: str = ""
    raciocinio: str = ""
    chamadas: list[dict[str, Any]] = field(default_factory=list)  # [{id, nome, args, args_brutos}]
    tokens_prompt: int = 0
    tokens_saida: int = 0
    segundos: float = 0.0
    pp_tps: float | None = None  # prefill tok/s (timings do llama-server)
    tg_tps: float | None = None  # decode tok/s
    fim: str = ""  # finish_reason
    erro: str = ""
    mensagem_bruta: dict[str, Any] = field(default_factory=dict)

    def resumo(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d.pop("mensagem_bruta", None)
        return d


def _parse_args(bruto: Any) -> tuple[dict[str, Any] | None, str]:
    if isinstance(bruto, dict):
        return bruto, json.dumps(bruto, ensure_ascii=False)
    texto = bruto if isinstance(bruto, str) else ""
    try:
        val = json.loads(texto) if texto.strip() else {}
        return (val if isinstance(val, dict) else None), texto
    except json.JSONDecodeError:
        return None, texto


class Cliente:
    def __init__(self, base: str = "http://127.0.0.1:8080", timeout: float = 300.0,
                 pensamento: bool = False, template_kwargs: dict | None = None,
                 folga_pensamento: int = 0):
        self.base = base.rstrip("/").removesuffix("/v1")
        self.timeout = timeout
        self.pensamento = pensamento
        self.template_kwargs = template_kwargs
        self.folga_pensamento = folga_pensamento  # tokens extras por chamada para o raciocínio

    # ---------- HTTP ----------
    def _req(self, metodo: str, caminho: str, corpo: dict | None = None,
             timeout: float | None = None) -> dict:
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", "replace")[:500]
            raise ErroCliente(f"HTTP {e.code} em {caminho}: {detalhe}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise ErroCliente(f"falha em {caminho}: {e}") from e

    def saude(self) -> dict:
        try:
            return self._req("GET", "/health", timeout=5)
        except ErroCliente:
            return self._req("GET", "/v1/models", timeout=5)

    def modelos(self) -> dict:
        return self._req("GET", "/v1/models", timeout=5)

    def propriedades(self) -> dict:
        try:
            return self._req("GET", "/props", timeout=5)
        except ErroCliente:
            return {}

    def contar_tokens(self, texto: str) -> int:
        r = self._req("POST", "/tokenize", {"content": texto}, timeout=60)
        return len(r.get("tokens", []))

    # ---------- chat ----------
    def chat(self, mensagens: list[dict], max_tokens: int, temperatura: float = 0.0,
             seed: int = 1234, ferramentas: list[dict] | None = None,
             extra: dict | None = None, exato: bool = False) -> Resposta:
        """`exato=True` não soma a folga de raciocínio (medição de velocidade)."""
        if self.pensamento and not exato:
            max_tokens += self.folga_pensamento
        corpo: dict[str, Any] = {
            "model": "local",
            "messages": mensagens,
            "max_tokens": max_tokens,
            "temperature": temperatura,
            "seed": seed,
            "stream": False,
        }
        if temperatura == 0:
            corpo["top_k"] = 1
        if ferramentas:
            corpo["tools"] = ferramentas
            corpo["tool_choice"] = "auto"
        if self.template_kwargs is not None:
            corpo["chat_template_kwargs"] = self.template_kwargs
        elif not self.pensamento:
            corpo["chat_template_kwargs"] = {"enable_thinking": False}
        if extra:
            corpo.update(extra)

        t0 = time.monotonic()
        try:
            dados = self._req("POST", "/v1/chat/completions", corpo)
        except ErroCliente as e:
            return Resposta(erro=str(e), segundos=time.monotonic() - t0)
        seg = time.monotonic() - t0

        escolha = (dados.get("choices") or [{}])[0]
        msg = escolha.get("message") or {}
        texto = msg.get("content") or ""
        raciocinio = msg.get("reasoning_content") or ""
        m = RE_THINK.search(texto)
        if m:  # template sem reasoning-format: separa o <think> manualmente
            raciocinio = raciocinio or m.group(0)
            texto = RE_THINK.sub("", texto)
        if "<think>" in texto and "</think>" not in texto:  # cortado no meio do raciocínio
            raciocinio, texto = texto, ""

        chamadas = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args, brutos = _parse_args(fn.get("arguments"))
            chamadas.append({"id": tc.get("id") or f"call_{i}", "nome": fn.get("name", ""),
                             "args": args, "args_brutos": brutos})

        uso = dados.get("usage") or {}
        tim = dados.get("timings") or {}
        saida = int(uso.get("completion_tokens") or tim.get("predicted_n") or 0)
        tg = tim.get("predicted_per_second")
        if tg is None and saida and seg > 0:
            tg = saida / seg
        return Resposta(
            texto=texto.strip(), raciocinio=raciocinio, chamadas=chamadas,
            tokens_prompt=int(uso.get("prompt_tokens") or tim.get("prompt_n") or 0),
            tokens_saida=saida, segundos=seg,
            pp_tps=tim.get("prompt_per_second"), tg_tps=tg,
            fim=escolha.get("finish_reason") or "", mensagem_bruta=msg,
        )
