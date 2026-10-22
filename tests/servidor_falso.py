"""Servidor HTTP que imita o llama-server, para ensaiar o pipeline sem GPU.

Uso direto: python3 -m tests.servidor_falso 8099
Respostas são enlatadas: código de referência quando reconhece o caso, "RESPOSTA: 42" no resto,
e uma tool_call para a primeira ferramenta oferecida (uma vez por conversa).
"""

from __future__ import annotations

import json
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIAS = {}
for c in tomllib.load(open(RAIZ / "suites" / "01_codigo.toml", "rb"))["caso"]:
    REFERENCIAS[c["prompt"][:60]] = c["referencia"]


def responder(corpo: dict) -> dict:
    msgs = corpo["messages"]
    ultima = msgs[-1]
    usuario = next((m["content"] for m in msgs if m["role"] == "user"), "")
    msg: dict = {"role": "assistant", "content": ""}
    ja_chamou = any(m["role"] == "tool" for m in msgs)
    if corpo.get("tools") and not ja_chamou and ultima["role"] == "user":
        fn = corpo["tools"][0]["function"]
        args = {k: "x" for k in fn["parameters"].get("required", [])}
        if fn["name"] == "obter_clima":
            args = {"cidade": "Belo Horizonte"}
        msg["tool_calls"] = [{"id": "call_1", "type": "function",
                              "function": {"name": fn["name"], "arguments": json.dumps(args)}}]
    elif usuario[:60] in REFERENCIAS:
        msg["content"] = "```python\n" + REFERENCIAS[usuario[:60]] + "\n```"
    elif corpo.get("tools") and any(t["function"]["name"] == "finalizar" for t in corpo["tools"]):
        msg["tool_calls"] = [{"id": "call_f", "type": "function",
                              "function": {"name": "finalizar", "arguments": '{"resposta": "feito"}'}}]
    else:
        msg["content"] = "Pensando rapidamente.\nRESPOSTA: 42"
    n = max(1, len(msg["content"].split()))
    return {"choices": [{"message": msg, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": n},
            "timings": {"prompt_n": 100, "prompt_per_second": 900.0, "predicted_n": n,
                        "predicted_per_second": 31.0}}


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
            return self._json({"tokens": list(range(int(len(corpo.get("content", "")) / 3.5)))})
        if self.path == "/v1/chat/completions":
            return self._json(responder(corpo))
        self._json({"erro": "404"}, 404)


def iniciar(porta: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8099), Handler)
    print(f"servidor falso em 127.0.0.1:{srv.server_address[1]}", flush=True)
    srv.serve_forever()
