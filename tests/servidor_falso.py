"""Servidor HTTP que imita o llama-server, para testar o pipeline sem GPU.

Uso direto (ensaio): python3 -m tests.servidor_falso 8099
Em testes: `with Servidor(responder) as s:` onde `responder(corpo) -> dict` devolve a `message` do
assistente, ou `(status_http, corpo)` para simular erro. Sem responder, usa respostas enlatadas:
código de referência quando reconhece o caso, `exemplo_bom` quando existe, "RESPOSTA: 42" no resto.
"""

from __future__ import annotations

import json
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parent.parent


def _enlatadas() -> dict[str, dict]:
    """prompt (60 primeiros caracteres) -> mensagem enlatada, a partir das próprias suítes."""
    out = {}
    for arq in sorted((RAIZ / "suites").glob("*.toml")):
        with open(arq, "rb") as f:
            for c in tomllib.load(f).get("caso", []):
                if "referencia" in c:
                    out[c["prompt"][:60]] = {"content": "```python\n" + c["referencia"] + "\n```"}
    return out


ENLATADAS = _enlatadas()


def responder_padrao(corpo: dict) -> dict:
    msgs = corpo["messages"]
    usuario = next((m["content"] for m in msgs if m["role"] == "user"), "")
    ja_chamou = any(m["role"] == "tool" for m in msgs)
    ferramentas = corpo.get("tools") or []
    if any(t["function"]["name"] == "finalizar" for t in ferramentas):
        return {"content": "", "tool_calls": [{"id": "call_f", "type": "function", "function": {
            "name": "finalizar", "arguments": '{"resposta": "feito"}'}}]}
    if ferramentas and not ja_chamou and msgs[-1]["role"] == "user":
        fn = ferramentas[0]["function"]
        args = {k: "x" for k in fn["parameters"].get("required", [])}
        if fn["name"] == "obter_clima":
            args = {"cidade": "Belo Horizonte"}
        return {"content": "", "tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": fn["name"], "arguments": json.dumps(args)}}]}
    if "PRONTO" in usuario:
        return {"content": "PRONTO"}
    if usuario[:60] in ENLATADAS:
        return ENLATADAS[usuario[:60]]
    return {"content": "Pensando rapidamente.\nRESPOSTA: 42"}


def _completar(msg: dict) -> dict:
    msg = dict(msg)
    fim = msg.pop("_fim", "stop")  # roteiros podem simular corte por limite ("length")
    n = max(1, len((msg.get("content") or "").split()))
    return {"choices": [{"message": {"role": "assistant", **msg}, "finish_reason": fim}],
            "usage": {"prompt_tokens": 100, "completion_tokens": n},
            "timings": {"prompt_n": 100, "prompt_per_second": 900.0, "predicted_n": n,
                        "predicted_per_second": 31.0}}


class Servidor:
    def __init__(self, responder: Callable[[dict], object] | None = None, porta: int = 0):
        self.responder = responder or responder_padrao
        self.requisicoes: list[dict] = []
        servidor = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, dados: dict, codigo: int = 200) -> None:
                b = json.dumps(dados).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                if self.path == "/health":
                    return self._json({"status": "ok"})
                if self.path == "/v1/models":
                    return self._json({"data": [{"id": "falso"}]})
                if self.path == "/props":
                    return self._json({"default_generation_settings": {"n_ctx": 16384}})
                self._json({"erro": "404"}, 404)

            def do_POST(self):
                corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
                if self.path == "/tokenize":
                    # ~3,5 caracteres por token, como um tokenizer BPE em português
                    return self._json({"tokens": list(range(int(len(corpo.get("content", "")) / 3.5)))})
                if self.path == "/v1/chat/completions":
                    servidor.requisicoes.append(corpo)
                    r = servidor.responder(corpo)
                    if isinstance(r, tuple):
                        return self._json(r[1], r[0])
                    return self._json(_completar(r))
                self._json({"erro": "404"}, 404)

        self.http = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
        self.http.daemon_threads = True

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.http.server_address[1]}"

    def __enter__(self) -> "Servidor":
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc) -> None:
        self.http.shutdown()
        self.http.server_close()


def roteiro(*mensagens) -> Callable[[dict], object]:
    """Responder que devolve as mensagens em sequência (a última se repete)."""
    fila = list(mensagens)

    def responder(corpo: dict):
        return fila.pop(0) if len(fila) > 1 else fila[0]
    return responder


def chamada(nome: str, args: dict | str, id_: str = "c1") -> dict:
    """Mensagem de assistente com uma tool call."""
    return {"content": "", "tool_calls": [{"id": id_, "type": "function", "function": {
        "name": nome, "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}}]}


if __name__ == "__main__":
    s = Servidor(porta=int(sys.argv[1]) if len(sys.argv) > 1 else 8099)
    print(f"servidor falso em {s.url}", flush=True)
    try:
        s.http.serve_forever()
    finally:
        s.http.server_close()
