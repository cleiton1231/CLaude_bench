"""Ajudantes comuns dos testes."""

import contextlib
import io
import json
import os
import shutil
import tempfile
import tomllib
import unittest
from contextlib import contextmanager
from pathlib import Path

from prova.cliente import Cliente, Resposta

RAIZ = Path(__file__).resolve().parent.parent


def R(texto: str = "", chamadas: list | None = None, **kw) -> Resposta:
    return Resposta(texto=texto, chamadas=chamadas or [], **kw)


def chamada(nome: str, args: dict) -> dict:
    return {"id": "c", "nome": nome, "args": args, "args_brutos": json.dumps(args, ensure_ascii=False)}


def toml_suite(nome: str) -> dict:
    with open(RAIZ / "suites" / nome, "rb") as f:
        return tomllib.load(f)


def cliente(url: str, **kw) -> Cliente:
    c = Cliente(url, timeout=10, **kw)
    c.espera_retentativa = 0.01
    return c


@contextmanager
def ambiente(**vars_):
    """Define variáveis de ambiente temporariamente (None remove)."""
    antigo = {k: os.environ.get(k) for k in vars_}
    try:
        for k, v in vars_.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in antigo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ComTmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prova_teste_"))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))  # progresso das etapas não polui a saída

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
