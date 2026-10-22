"""Scripts de shell e CLI, de ponta a ponta, com um llama-server falso (sem GPU, sem modelo)."""

import json
import os
import shutil
import socket
import subprocess
import sys
import unittest

from tests.gguf_falso import QWEN14, escrever
from tests.util import RAIZ, ComTmp

SCRIPTS = sorted((RAIZ / "scripts").glob("*.sh"))
FALSO = RAIZ / "tests" / "llama_server_falso"


def porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def rodar(cmd, env=None, timeout=240, entrada=None):
    e = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=RAIZ, env=e, capture_output=True, text=True, timeout=timeout, input=entrada)


class TestSintaxe(unittest.TestCase):
    def test_bash_n(self):
        for s in SCRIPTS:
            with self.subTest(s.name):
                self.assertEqual(rodar(["bash", "-n", str(s)]).returncode, 0)

    def test_executaveis(self):
        for s in SCRIPTS:
            with self.subTest(s.name):
                self.assertTrue(os.access(s, os.X_OK), f"{s.name} sem chmod +x")

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck não instalado")
    def test_shellcheck(self):
        r = rodar(["shellcheck", "-S", "warning", "-x", *map(str, SCRIPTS)])
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_etapas_numeradas_existem(self):
        nomes = {s.name for s in SCRIPTS}
        for n in ("00_preflight", "01_subir_modelo", "02_sanidade", "03_desempenho", "04_suites", "05_agente",
                  "06_contexto", "07_consistencia", "08_pacote_juiz", "09_pontuar", "10_parar_modelo",
                  "11_criticos", "99_comparar", "instalar", "escolher", "rodar_modelo", "ensaio_sem_gpu",
                  "proximo", "piloto"):
            self.assertIn(f"{n}.sh", nomes)


class TestCLI(ComTmp):
    def prova(self, *args, env=None):
        return rodar([sys.executable, "-m", "prova", *args], env)

    def test_perfil_vira_variaveis_de_shell(self):
        perfil = self.tmp / "m.toml"
        perfil.write_text('nome = "M"\ngguf = "~/x.gguf"\nctx = 8192\nargs_extra = ["--n-cpu-moe", "8"]\n')
        script = f'eval "$({sys.executable} -m prova perfil {perfil})"; printf "%s\\n" "$PROVA_ID" "${{PROVA_FLAGS[@]}}"'
        r = rodar(["bash", "-c", script])
        linhas = r.stdout.split("\n")
        self.assertEqual(linhas[0], "m")
        for f in ("--jinja", "8192", "--n-cpu-moe", "-ctk", "q8_0"):
            self.assertIn(f, linhas)

    def test_estimativa_da_completa_fica_na_faixa(self):
        # o pedido do projeto: 30–40 min por modelo a ~30 tok/s
        r = self.prova("estimar", "--tps", "30", env={"PROVA_RODADA": "completa"})
        linha = next(ln for ln in r.stdout.splitlines() if ln.startswith("total estimado"))
        minutos = int(linha.split("~")[1].split()[0])
        self.assertTrue(28 <= minutos <= 42, linha)

    def test_etapa_ativa(self):
        env = {"PROVA_RODADA": "velocidade"}
        self.assertEqual(self.prova("etapa-ativa", "contexto", env=env).returncode, 0)
        self.assertEqual(self.prova("etapa-ativa", "suites", env=env).returncode, 1)

    def test_escolher_direto_e_rodada(self):
        sel = self.tmp / "selecao.toml"
        r = self.prova("escolher", "codigo", "--suites", "codigo,ferramentas", env={"PROVA_SELECAO": str(sel)})
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.prova("rodada", env={"PROVA_SELECAO": str(sel)})
        dados = json.loads(r.stdout.split("\ncategorias")[0])
        self.assertEqual(dados["suites"], ["codigo", "ferramentas"])
        self.assertEqual(self.prova("rodada", "--nome", env={"PROVA_SELECAO": str(sel)}).stdout.strip(),
                         "codigo (ajustada)")

    def test_escolher_interativo(self):
        sel = self.tmp / "selecao.toml"
        rapida = sorted(p.stem for p in (RAIZ / "config" / "rodadas").glob("*.toml")).index("rapida") + 1
        r = rodar([sys.executable, "-m", "prova", "escolher"], {"PROVA_SELECAO": str(sel)},
                  entrada=f"{rapida}\ns\n1,5\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('rodada = "rapida"', sel.read_text())
        self.assertIn('suites = ["codigo", "ferramentas"]', sel.read_text())

    def test_selecao_invalida_da_erro_claro(self):
        sel = self.tmp / "selecao.toml"
        sel.write_text('rodada = "inventada"\n')
        r = self.prova("validar", env={"PROVA_SELECAO": str(sel)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("não existe", r.stderr)

    def test_novo_perfil(self):
        g = escrever(self.tmp / "Qwen3-14B-Q4_K_M.gguf", QWEN14, int(8.4 * 2**30))
        r = self.prova("novo-perfil", str(g), env={"PROVA_DIR_MODELOS": str(self.tmp)})
        self.assertIn("criado", r.stdout)
        self.assertTrue((self.tmp / "qwen3-14b-q4-k-m.toml").exists())

    def test_sandbox_e_validar(self):
        self.assertIn("nível efetivo", self.prova("sandbox").stdout)
        self.assertEqual(self.prova("validar").returncode, 0)


class TestCicloCompleto(ComTmp):
    """01 → 02 → 04 → 09 → 10 com um llama-server falso numa porta livre."""

    def setUp(self):
        super().setUp()
        self.porta = porta_livre()
        self.res = self.tmp / "resultados"
        self.modelos = self.tmp / "modelos"
        self.modelos.mkdir()
        gguf = self.tmp / "falso.gguf"
        gguf.write_bytes(b"GGUF")
        (self.modelos / "falso.toml").write_text(f'nome = "Falso"\ngguf = "{gguf}"\nctx = 8192\n')
        self.env = {"PROVA_BIN": str(FALSO), "PROVA_PORTA": str(self.porta), "PROVA_RESULTADOS": str(self.res),
                    "PROVA_DIR_MODELOS": str(self.modelos), "PROVA_RODADA": "rapida",
                    "PROVA_SUITES": "raciocinio", "PROVA_ETAPAS": "suites"}

    def tearDown(self):
        rodar(["scripts/10_parar_modelo.sh"], self.env)
        super().tearDown()

    def test_ciclo(self):
        r = rodar(["scripts/01_subir_modelo.sh", str(self.modelos / "falso.toml")], self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("pronto em", r.stdout)
        self.assertTrue((self.res / ".servidor.pid").exists())
        r = rodar(["scripts/02_sanidade.sh", "falso"], self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = rodar(["scripts/04_suites.sh", "falso"], self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = rodar(["scripts/05_agente.sh", "falso"], self.env)
        self.assertIn("desligada", r.stdout)
        r = rodar(["scripts/09_pontuar.sh", "falso"], self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        placar = json.loads((self.res / "falso" / "placar.json").read_text())
        self.assertEqual(list(placar["categorias"]), ["raciocinio"])
        self.assertTrue(placar["completo"], placar)
        r = rodar(["scripts/10_parar_modelo.sh"], self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("servidor parado", r.stdout)
        self.assertFalse((self.res / ".servidor.pid").exists())

    def test_parar_nao_mata_servidor_de_outra_porta(self):
        outra = porta_livre()
        alheio = subprocess.Popen([str(FALSO), "--model", str(self.tmp / "falso.gguf"), "--port", str(outra)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            r = rodar(["scripts/10_parar_modelo.sh"], self.env)
            self.assertEqual(r.returncode, 0)
            self.assertIsNone(alheio.poll(), "o 10 matou um llama-server que não era da prova")
        finally:
            alheio.kill()
            alheio.wait()

    def test_01_falha_com_mensagem_se_o_servidor_morre(self):
        (self.modelos / "quebrado.toml").write_text('nome = "Q"\ngguf = "/nao/existe.gguf"\n')
        r = rodar(["scripts/01_subir_modelo.sh", str(self.modelos / "quebrado.toml")], self.env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GGUF não encontrado", r.stdout + r.stderr)

    def test_preflight(self):
        r = rodar(["scripts/00_preflight.sh", str(self.modelos / "falso.toml")],
                  {**self.env, "PROVA_PREFLIGHT_SEM_TESTES": "1"})
        self.assertIn("[ok]   llama-server", r.stdout)
        self.assertIn("total estimado", r.stdout)
        self.assertNotIn("[FALHA]", r.stdout, r.stdout)


class TestEnsaioEInstalacao(ComTmp):
    def test_ensaio_sem_gpu(self):
        res = self.tmp / "res"
        r = rodar(["scripts/ensaio_sem_gpu.sh"], {"PROVA_RESULTADOS": str(res),
                                                  "PROVA_PORTA_ENSAIO": str(porta_livre())}, timeout=400)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])
        d = res / "ensaio"
        for arq in ("relatorio.md", "placar.json", "pacote_juiz.md", "agente.jsonl", "contexto.jsonl",
                    "consistencia.json", "criticos.json", "desempenho.json"):
            self.assertTrue((d / arq).exists(), arq)
        placar = json.loads((d / "placar.json").read_text())
        self.assertEqual(placar["categorias"]["codigo"]["nota"], 1000)  # respostas enlatadas = referência
        self.assertEqual(placar["erros_infra"], [])

    def test_instalar_auto(self):
        modelos_gguf = self.tmp / "ggufs"
        modelos_gguf.mkdir()
        escrever(modelos_gguf / "Qwen3-14B-Q4_K_M.gguf", QWEN14, int(8.4 * 2**30))
        escrever(modelos_gguf / "mmproj-Qwen3.gguf", QWEN14)  # projetor de visão: deve ser ignorado
        env = {"PROVA_CONFIG_LOCAL": str(self.tmp / "local.toml"), "PROVA_SELECAO": str(self.tmp / "sel.toml"),
               "PROVA_DIR_MODELOS": str(self.tmp / "perfis")}
        r = rodar(["scripts/instalar.sh", "--auto", "--bin", str(FALSO), "--modelos", str(modelos_gguf),
                   "--rodada", "rapida", "--sem-validar"], env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(str(FALSO), (self.tmp / "local.toml").read_text())
        self.assertIn('rodada = "rapida"', (self.tmp / "sel.toml").read_text())
        perfis = sorted(p.name for p in (self.tmp / "perfis").glob("*.toml"))
        self.assertEqual(perfis, ["qwen3-14b-q4-k-m.toml"])


if __name__ == "__main__":
    unittest.main()
