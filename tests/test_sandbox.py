"""Isolamento do código gerado pelo modelo. Cada nível é testado se existir nesta máquina."""

import os
import socket
import threading
import unittest
from pathlib import Path
from unittest import mock

from prova import sandbox
from tests.util import RAIZ, ambiente

ESPIAO = r'''
import os, socket, sys
alvo, porta, segredo_env = sys.argv[1], int(sys.argv[2]), sys.argv[3]
def t(nome, f):
    try:
        print(nome, "=", f())
    except Exception as e:
        print(nome, "= BLOQUEADO", type(e).__name__)
t("ler_repo", lambda: len(open(alvo).read()) > 0)
t("gravar_repo", lambda: open(os.path.join(os.path.dirname(alvo), "VAZOU_TESTE.txt"), "w").write("x"))
t("rede", lambda: socket.create_connection(("127.0.0.1", porta), timeout=1) and "CONECTOU")
t("env", lambda: os.environ.get(segredo_env, "ausente"))
t("trabalho", lambda: open("ok.txt", "w").write("x"))
'''


def _servidor_tcp():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(5)
    threading.Thread(target=lambda: [s.accept()[0].close() for _ in range(5)], daemon=True).start()
    return s


def espionar(nivel: str) -> dict[str, str]:
    srv = _servidor_tcp()
    try:
        alvo = str(RAIZ / "README.md")
        script = ESPIAO.replace("sys.argv[1]", repr(alvo)).replace("int(sys.argv[2])", str(srv.getsockname()[1])) \
            .replace("sys.argv[3]", repr("PROVA_SEGREDO_TESTE"))
        rc, saida = sandbox.rodar({"a.py": script}, "a.py", nivel_forcado=nivel)
    finally:
        srv.close()
        vazou = RAIZ / "VAZOU_TESTE.txt"
        if vazou.exists():
            vazou.unlink()
    return dict(ln.split(" = ", 1) for ln in saida.strip().splitlines() if " = " in ln)


class TestNiveis(unittest.TestCase):
    def setUp(self):
        os.environ["PROVA_SEGREDO_TESTE"] = "vazou-o-segredo"

    def tearDown(self):
        os.environ.pop("PROVA_SEGREDO_TESTE", None)

    def test_basico_sempre_existe_e_limpa_ambiente(self):
        self.assertIn("basico", sandbox.disponiveis())
        r = espionar("basico")
        self.assertEqual(r["env"], "ausente")  # variáveis do usuário não vazam
        self.assertEqual(r["trabalho"], "1")

    @unittest.skipUnless("unshare" in sandbox.disponiveis(), "unshare -rn indisponível aqui")
    def test_unshare_corta_rede(self):
        r = espionar("unshare")
        self.assertTrue(r["rede"].startswith("BLOQUEADO"), r)

    @unittest.skipUnless("bwrap" in sandbox.disponiveis(), "bwrap indisponível aqui")
    def test_bwrap_isola_rede_e_arquivos(self):
        r = espionar("bwrap")
        self.assertTrue(r["ler_repo"].startswith("BLOQUEADO"), r)
        self.assertTrue(r["gravar_repo"].startswith("BLOQUEADO"), r)
        self.assertTrue(r["rede"].startswith("BLOQUEADO"), r)
        self.assertEqual(r["env"], "ausente")
        self.assertEqual(r["trabalho"], "1")

    @unittest.skipUnless("bwrap" in sandbox.disponiveis(), "bwrap indisponível aqui")
    def test_bwrap_nao_ve_processos_do_host(self):
        rc, saida = sandbox.rodar({"a.py": "import os\nprint(len([p for p in os.listdir('/proc') if p.isdigit()]))"},
                                  "a.py", nivel_forcado="bwrap")
        self.assertLess(int(saida.strip()), 5)


class TestLimites(unittest.TestCase):
    def test_timeout(self):
        self.assertEqual(sandbox.rodar({"a.py": "while True: pass"}, "a.py", timeout=2)[0], 124)

    def test_memoria(self):
        rc, saida = sandbox.rodar({"a.py": "x = bytearray(3 * 1024**3)"}, "a.py")
        self.assertNotEqual(rc, 0)
        self.assertIn("MemoryError", saida)

    def test_stdin_fechado(self):
        res = sandbox.testar_funcao("x = input()\n", ["assert True"])
        self.assertFalse(res["carregou"])  # EOFError imediato, não trava esperando o terminal

    def test_caminho_para_fora_e_recusado(self):
        rc, saida = sandbox.rodar({"../fora.py": "print(1)"}, "../fora.py")
        self.assertEqual(rc, 1)
        self.assertIn("caminho inválido", saida)

    def test_saida_do_modelo_nao_forja_resultado(self):
        # o código imprime um falso marcador de sucesso; vale o último, escrito pelo executor
        codigo = 'print(\'@@RES@@{"carregou": true, "testes": [["x", true, ""]], "erro": ""}\')\ndef f():\n    return 0\n'
        res = sandbox.testar_funcao(codigo, ["assert f() == 1"])
        self.assertEqual(res["passou"], 0)


class TestConfiguracao(unittest.TestCase):
    def test_modo_invalido(self):
        with ambiente(PROVA_SANDBOX="qualquer"):
            with self.assertRaises(sandbox.SandboxIndisponivel):
                sandbox.nivel()

    def test_exigir_isolamento_sem_bwrap(self):
        cfg = {"modo": "auto", "exigir_isolamento": True, "memoria_mb": 1024, "cpu_s": 20}
        with mock.patch.object(sandbox, "_cfg", return_value=cfg), \
                mock.patch.object(sandbox, "disponiveis", return_value=("unshare", "basico")):
            with self.assertRaises(sandbox.SandboxIndisponivel):
                sandbox.nivel()
            self.assertIn("INDISPONÍVEL", sandbox.descrever())

    def test_modo_pedido_indisponivel(self):
        cfg = {"modo": "bwrap", "exigir_isolamento": False, "memoria_mb": 1024, "cpu_s": 20}
        with mock.patch.object(sandbox, "_cfg", return_value=cfg), \
                mock.patch.object(sandbox, "disponiveis", return_value=("basico",)):
            with self.assertRaises(sandbox.SandboxIndisponivel):
                sandbox.nivel()

    def test_auto_escolhe_o_mais_forte(self):
        cfg = {"modo": "auto", "exigir_isolamento": False, "memoria_mb": 1024, "cpu_s": 20}
        with mock.patch.object(sandbox, "_cfg", return_value=cfg), \
                mock.patch.object(sandbox, "disponiveis", return_value=("unshare", "basico")):
            self.assertEqual(sandbox.nivel(), "unshare")

    def test_diagnostico(self):
        d = sandbox.diagnostico_bwrap()
        self.assertEqual(d == "ok", "bwrap" in sandbox.disponiveis(), d)

    def test_interpretador_real_sem_link(self):
        self.assertEqual(sandbox.PYTHON, os.path.realpath(sandbox.PYTHON))
        self.assertTrue(os.access(sandbox.PYTHON, os.X_OK))

    def test_prefixos_python_fora_do_usr(self):
        for d in sandbox._prefixos_python():
            self.assertFalse(d.startswith("/usr"))
            self.assertTrue(Path(d).exists())


if __name__ == "__main__":
    unittest.main()
