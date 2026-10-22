"""Testes offline. Isolados da configuração e dos resultados do usuário: nenhum teste lê
config/local.toml nem config/selecao.toml, nada é gravado em resultados/, e nenhum teste usa GPU,
modelo ou rede externa."""

import atexit
import os
import shutil
import tempfile

_RES = tempfile.mkdtemp(prefix="prova_resultados_")
atexit.register(shutil.rmtree, _RES, True)
os.environ["PROVA_RESULTADOS"] = _RES
os.environ["PROVA_CONFIG_LOCAL"] = "/nao/existe/local.toml"
os.environ["PROVA_SELECAO"] = "/nao/existe/selecao.toml"
for _v in ("PROVA_RODADA", "PROVA_SUITES", "PROVA_ETAPAS", "PROVA_SANDBOX", "PROVA_PORTA", "PROVA_HOST",
           "PROVA_SEED", "PROVA_BIN", "PROVA_DIR_MODELOS"):
    os.environ.pop(_v, None)
