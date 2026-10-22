"""Planejador (`prova proximo`) e piloto automático."""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from prova import config, piloto, plano
from tests.servidor_falso import Servidor
from tests.test_scripts import FALSO, porta_livre, rodar
from tests.util import RAIZ, ComTmp, ambiente


class Estado(ComTmp):
    """Monta um mundo isolado: perfis, resultados e servidor falsos."""

    def setUp(self):
        super().setUp()
        self.modelos = self.tmp / "modelos"
        self.res = self.tmp / "res"
        self.modelos.mkdir()
        self.res.mkdir()
        self.porta = porta_livre()
        self.patches = [mock.patch.object(config, "MODELOS", self.modelos),
                        mock.patch.object(config, "RESULTADOS", self.res)]
        for p in self.patches:
            p.start()
        self.env = ambiente(PROVA_BIN=FALSO, PROVA_PORTA=self.porta, PROVA_RODADA="rapida",
                            PROVA_SUITES="raciocinio", PROVA_ETAPAS="suites",
                            PROVA_SERIE=self.tmp / "serie.toml")
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__(None, None, None)
        for p in self.patches:
            p.stop()
        super().tearDown()

    def perfil(self, mid):
        (self.modelos / f"{mid}.toml").write_text(f'nome = "{mid}"\ngguf = "/x.gguf"\n')

    def meta(self, mid, **campos):
        d = self.res / mid
        d.mkdir(exist_ok=True)
        (d / "meta.json").write_text(json.dumps(campos))
        return d


class TestDecisoes(Estado):
    def test_sem_perfis(self):
        self.assertEqual(plano.proximo()["acao"], "configurar")

    def test_sem_llama_server(self):
        self.perfil("m")
        with ambiente(PROVA_BIN="/nao/existe/llama-server"):
            a = plano.proximo()
        self.assertEqual(a["acao"], "configurar")
        self.assertIn("instalar.sh", a["comando"][0])

    def test_comeca_subindo_o_primeiro_modelo(self):
        self.perfil("b")
        self.perfil("a")
        self.perfil("exemplo-ignorado")
        a = plano.proximo()
        self.assertEqual((a["acao"], a["modelo"]), ("rodar", "a"))
        self.assertEqual(a["comando"], ["scripts/01_subir_modelo.sh", str(self.modelos / "a.toml")])
        self.assertTrue(a["conferir"])

    def test_serie_define_ordem_e_valida_perfis(self):
        self.perfil("a")
        self.perfil("b")
        (self.tmp / "serie.toml").write_text('modelos = ["b", "a"]\n')
        self.assertEqual(plano.proximo()["modelo"], "b")
        (self.tmp / "serie.toml").write_text('modelos = ["b", "zzz"]\n')
        a = plano.proximo()
        self.assertEqual(a["acao"], "bloqueado")
        self.assertIn("zzz", a["motivo"])

    def test_servidor_e_sanidade(self):
        self.perfil("a")
        self.perfil("b")
        (self.res / ".servidor.id").write_text("b")
        with Servidor(porta=self.porta):
            a = plano.proximo()
            self.assertEqual((a["comando"], a["modelo"]), (["scripts/10_parar_modelo.sh"], "a"))  # b ocupa o servidor
            (self.res / ".servidor.id").write_text("a")
            self.meta("a", sanidade=None)
            self.assertEqual(plano.proximo()["comando"], ["scripts/02_sanidade.sh", "a"])
            self.meta("a", sanidade={"ok": False, "problemas": ["template quebrado"]})
            a = plano.proximo()
            self.assertEqual(a["acao"], "bloqueado")
            self.assertIn("template quebrado", a["motivo"])
            self.meta("a", sanidade={"ok": True})
            a = plano.proximo()
            self.assertEqual((a["comando"], a["etapa"]), (["scripts/04_suites.sh", "a"], "suites"))

    def test_sandbox_exigida_ausente_bloqueia(self):
        from prova import sandbox
        self.perfil("a")
        with mock.patch.object(sandbox, "nivel", side_effect=sandbox.SandboxIndisponivel("sem bwrap")):
            self.assertEqual(plano.proximo()["acao"], "bloqueado")

    def test_aguarda_execucao_em_segundo_plano(self):
        self.perfil("a")
        outro = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            (self.res / ".piloto.pid").write_text(str(outro.pid))
            self.assertEqual(plano.proximo()["acao"], "aguardar")
        finally:
            outro.kill()
            outro.wait()
        self.assertNotEqual(plano.proximo()["acao"], "aguardar")  # pid morto não trava

    def test_notas_e_parecer_invalidos(self):
        d = self.meta("a")
        (d / "notas_juiz.json").write_text(json.dumps({"casos": {"x.a": {"nota": 5, "motivo": "m"},
                                                                 "x.b": {"nota": 2, "motivo": ""}}}))
        regs = [{"id": i, "suite": "ceticismo", "categoria": "ceticismo", "dificuldade": "medio",
                 "avaliacao": "juiz", "q_auto": None, "checks": []} for i in ("x.a", "x.b", "x.c")]
        (d / "suites").mkdir()
        (d / "suites" / "ceticismo.jsonl").write_text("".join(json.dumps(r) + "\n" for r in regs))
        sel = {"etapas": ["suites"], "suites": ["ceticismo"], "dificuldades": ["facil", "medio", "dificil"],
               "incluir": [], "excluir": []}
        faltam, probs = plano.juiz_pendente(d, sel)
        self.assertEqual(faltam, ["x.c"])
        self.assertEqual(len(probs), 2)
        (d / "parecer.md").write_text("**Veredito:** bom\n### Pontos fortes\n")
        probs = plano.problemas_parecer(d)
        self.assertIn("falta a seção ### Falhas graves", probs)
        self.assertTrue(any("Confiança" in p for p in probs))

    def test_saida_texto_e_json(self):
        self.perfil("a")
        a = plano.proximo()
        t = plano.texto(a, plano.progresso(), "rapida")
        self.assertIn("PRÓXIMA AÇÃO: RODAR (a)", t)
        self.assertIn("comando: scripts/01_subir_modelo.sh", t)
        r = rodar([sys.executable, "-m", "prova", "proximo", "--json"],
                  {"PROVA_DIR_MODELOS": str(self.modelos), "PROVA_RESULTADOS": str(self.res)})
        dados = json.loads(r.stdout)
        self.assertEqual(dados["acao"], "rodar")
        self.assertEqual(dados["progresso"], [{"modelo": "a", "estado": "não iniciado"}])


class TestPiloto(Estado):
    def com_roteiro(self, *acoes):
        fila = list(acoes)
        return mock.patch.object(plano, "proximo", side_effect=lambda: fila.pop(0))

    def test_executa_ate_precisar_do_agente(self):
        r = {"acao": "rodar", "comando": ["true"], "motivo": "m"}
        with self.com_roteiro(r, r, {**plano._acao("julgar", "sua vez", "a")}), \
                mock.patch.object(plano, "progresso", return_value=[]), \
                mock.patch("subprocess.run", wraps=subprocess.run) as run:
            self.assertEqual(piloto.rodar(), 10)
        self.assertEqual(run.call_count, 2)
        self.assertFalse((self.res / ".piloto.pid").exists())

    def test_codigos_de_saida(self):
        for acao, codigo in (("fim", 0), ("parecer", 10), ("corrigir", 10), ("bloqueado", 20), ("configurar", 20)):
            with self.subTest(acao), self.com_roteiro(plano._acao(acao, "x")), \
                    mock.patch.object(plano, "progresso", return_value=[]):
                self.assertEqual(piloto.rodar(), codigo)

    def test_para_se_o_mesmo_comando_falha_duas_vezes(self):
        r = {"acao": "rodar", "comando": ["false"], "motivo": "m", "se_falhar": "reporte"}
        with self.com_roteiro(r, r, r):
            self.assertEqual(piloto.rodar(), 1)

    def test_limite_de_passos(self):
        r = {"acao": "rodar", "comando": ["true"], "motivo": "m"}
        with mock.patch.object(plano, "proximo", return_value=r):
            self.assertEqual(piloto.rodar(max_passos=3), 1)


class TestSerieCompleta(ComTmp):
    """Dois modelos, rodada com juiz: o piloto faz o mecânico e um agente simulado faz o resto."""

    def test_piloto_e_agente_simulado_ate_o_fim(self):
        m = self.tmp / "m"
        m.mkdir()
        (self.tmp / "f.gguf").write_bytes(b"GGUF")
        for mid in ("alfa", "beta"):
            (m / f"{mid}.toml").write_text(f'nome = "{mid}"\ngguf = "{self.tmp / "f.gguf"}"\nctx = 8192\n')
        env = {"PROVA_BIN": str(FALSO), "PROVA_PORTA": str(porta_livre()), "PROVA_RESULTADOS": str(self.tmp / "res"),
               "PROVA_DIR_MODELOS": str(m), "PROVA_RODADA": "completa", "PROVA_SUITES": "ceticismo,raciocinio",
               "PROVA_ETAPAS": "suites", "PROVA_SERIE": str(self.tmp / "nao.toml")}
        vezes = []
        try:
            for _ in range(10):
                r = rodar(["scripts/piloto.sh"], env, timeout=300)
                if r.returncode == 0:
                    break
                self.assertEqual(r.returncode, 10, r.stdout[-1500:])
                a = json.loads(rodar([sys.executable, "-m", "prova", "proximo", "--json"], env).stdout)
                vezes.append((a["acao"], a["modelo"]))
                if a["acao"] == "julgar":
                    notas = json.loads(Path(a["modelo_arquivo"]).read_text())
                    notas["casos"] = {k: {"nota": 2, "motivo": "teste"} for k in notas["casos"]}
                    Path(a["escrever"]).write_text(json.dumps(notas))
                elif a["acao"] == "parecer":
                    Path(a["escrever"]).write_text(
                        "**Veredito:** x\n**Nota geral:** 1 · **Confiança:** baixa — teste\n### Pontos fortes\n"
                        "### Pontos fracos\n### Falhas graves\n### Uso recomendado\n### Configuração\n### Comparação\n")
            else:
                self.fail(f"não terminou: {vezes}")
        finally:
            rodar(["scripts/10_parar_modelo.sh"], env)
        self.assertEqual(vezes, [("julgar", "alfa"), ("julgar", "beta"), ("parecer", "alfa"), ("parecer", "beta")])
        res = self.tmp / "res"
        self.assertTrue((res / "comparativo.md").exists())
        for mid in ("alfa", "beta"):
            placar = json.loads((res / mid / "placar.json").read_text())
            self.assertTrue(placar["completo"], mid)
            self.assertIn("Parecer do juiz", (res / mid / "relatorio.md").read_text())
        self.assertFalse((res / ".servidor.pid").exists())  # VRAM liberada no fim


class TestArquivosDoAgente(unittest.TestCase):
    def test_agents_md_e_claude_md(self):
        agents = (RAIZ / "AGENTS.md").read_text()
        for trecho in ("prova proximo", "scripts/piloto.sh", "julgar", "parecer", "corrigir", "armadilhas"):
            self.assertIn(trecho, agents)
        self.assertIn("@AGENTS.md", (RAIZ / "CLAUDE.md").read_text())

    def test_toda_acao_do_plano_esta_documentada(self):
        doc = plano.__doc__ + (RAIZ / "AGENTS.md").read_text()
        for acao in ("rodar", "julgar", "parecer", "corrigir", "bloqueado", "configurar", "aguardar", "fim"):
            self.assertIn(acao, doc)
        self.assertEqual(set(piloto.SAIDA) | {"rodar"},
                         {"rodar", "julgar", "parecer", "corrigir", "bloqueado", "configurar", "aguardar", "fim"})


if __name__ == "__main__":
    unittest.main()
