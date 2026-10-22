"""Geração de contexto longo, perfis a partir de GGUF e seleção de testes."""

import random
import re
import unittest

from prova import contexto, perfis, selecao
from tests.gguf_falso import QWEN14, escrever
from tests.servidor_falso import Servidor
from tests.util import ComTmp, ambiente, cliente


class TestContexto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Servidor().__enter__()
        cls.cli = cliente(cls.srv.url)
        cls.casos = contexto.gerar_casos(cls.cli, 16384, 1234)

    @classmethod
    def tearDownClass(cls):
        cls.srv.__exit__(None, None, None)

    def test_tamanhos_ate_o_ctx(self):
        self.assertEqual({c["tamanho"] for c in self.casos}, {4096, 8192, 16384})
        self.assertEqual({c["tamanho"] for c in contexto.gerar_casos(self.cli, 32768, 1)},
                         {4096, 8192, 16384, 32768})
        self.assertEqual(contexto.gerar_casos(self.cli, 2048, 1), [])

    def test_prompt_cabe_no_ctx_com_a_reserva(self):
        for ctx, reserva in ((16384, 700), (16384, 2800), (8192, 700)):
            for c in contexto.gerar_casos(self.cli, ctx, 7, reserva):
                with self.subTest(c["id"], ctx=ctx, reserva=reserva):
                    self.assertLessEqual(self.cli.contar_tokens(c["prompt"]), ctx - reserva)

    def test_busca_tem_resposta_unica_no_texto(self):
        for c in self.casos:
            if ".busca-" in c["id"]:
                codigo = c["checks"][0]["esperado"]
                nome = re.search(r"cujo responsável é (.+)\?", c["prompt"]).group(1)
                linha = next(ln for ln in c["prompt"].splitlines() if f"Responsável: {nome} |" in ln)
                self.assertIn(codigo, linha)
                self.assertEqual(c["prompt"].count(f"Responsável: {nome} |"), 1)

    def test_multisalto_com_atualizacao_exige_o_coordenador_novo(self):
        c = next(x for x in self.casos if x["id"].endswith("-atualizado"))
        projeto = re.search(r"coordena atualmente o projeto (\w+)", c["prompt"]).group(1)
        m = re.search(rf"a partir de hoje, (.+?) substitui (.+?) na coordenação do projeto {projeto}", c["prompt"])
        novo, antigo = m.groups()
        cod_novo = re.search(rf"Responsável: {novo} \|.*?Código: (\S+) \|", c["prompt"]).group(1)
        cod_antigo = re.search(rf"Responsável: {antigo} \|.*?Código: (\S+) \|", c["prompt"]).group(1)
        self.assertEqual(c["checks"][0]["esperado"], cod_novo)
        self.assertNotEqual(cod_novo, cod_antigo)

    def test_contagem_confere(self):
        c = next(x for x in self.casos if ".contagem-" in x["id"])
        setor = re.search(r"setor (\w+) estão", c["prompt"]).group(1)
        n = sum(1 for ln in c["prompt"].splitlines() if f"Setor: {setor} |" in ln and "Status: pendente" in ln)
        self.assertEqual(c["checks"][0]["esperado"], n)
        self.assertGreater(n, 0)

    def test_deterministico_pela_seed(self):
        a = contexto.gerar_casos(self.cli, 8192, 99)
        b = contexto.gerar_casos(self.cli, 8192, 99)
        c = contexto.gerar_casos(self.cli, 8192, 100)
        self.assertEqual([x["prompt"] for x in a], [x["prompt"] for x in b])
        self.assertNotEqual(a[0]["prompt"], c[0]["prompt"])

    def test_fichas_tem_codigos_e_nomes_unicos(self):
        f = contexto.gerar_fichas(random.Random(1), 800)
        self.assertEqual(len({x["codigo"] for x in f}), 800)
        self.assertEqual(len({x["nome"] for x in f}), 800)


class TestPerfis(ComTmp):
    def test_le_metadados_e_pula_tokenizer(self):
        g = escrever(self.tmp / "Qwen3-14B-Q4_K_M.gguf", QWEN14)
        m = perfis.ler_metadados(g)
        self.assertEqual(m["qwen3.block_count"], 40)
        self.assertNotIn("tokenizer.ggml.tokens", m)
        self.assertIn("tokenizer.chat_template", m)

    def test_kv_por_token(self):
        # 40 camadas × 8 cabeças KV × (128 + 128) × 1,0625 bytes (q8_0)
        self.assertEqual(perfis.kv_bytes_por_token(QWEN14, "q8_0"), 40 * 8 * 256 * 1.0625)
        self.assertEqual(perfis.kv_bytes_por_token(QWEN14, "f16"), 40 * 8 * 256 * 2)
        self.assertIsNone(perfis.kv_bytes_por_token({}))
        por_camada = {**QWEN14, "qwen3.attention.head_count_kv": [8, 0] * 20}  # híbrido: metade sem KV
        self.assertEqual(perfis.kv_bytes_por_token(por_camada, "f16"), 160 * 256 * 2)

    def test_ctx_sugerido(self):
        kv = perfis.kv_bytes_por_token(QWEN14)
        self.assertEqual(perfis.sugerir_ctx(8.4, kv, 40960, 16)[0], 32768)
        self.assertEqual(perfis.sugerir_ctx(8.4, kv, 8192, 16)[0], 8192)       # limite do modelo
        self.assertEqual(perfis.sugerir_ctx(13.0, kv, 40960, 16)[0], 16384)    # sobra 1,8 GiB; KV 16k = 1,33
        self.assertEqual(perfis.sugerir_ctx(14.0, kv, 40960, 16)[0], 8192)     # sobra 0,8 GiB
        ctx, avisos = perfis.sugerir_ctx(25.0, kv, 40960, 16)
        self.assertEqual(ctx, 4096)
        self.assertTrue(avisos)

    def test_gravar_perfil_valido(self):
        from prova import config
        g = escrever(self.tmp / "Qwen3-14B-Q4_K_M.gguf", QWEN14, int(8.4 * 2**30))
        arq, avisos = perfis.gravar_perfil(g, destino=self.tmp)
        self.assertEqual(arq.name, "qwen3-14b-q4-k-m.toml")
        p = config.perfil(arq)
        self.assertEqual((p["ctx"], p["quant"], p["pensamento"]), (32768, "Q4_K_M", False))
        self.assertIn("suporta raciocínio", arq.read_text())
        self.assertEqual(perfis.gravar_perfil(g, destino=self.tmp)[0], None)  # não sobrescreve
        self.assertIsNotNone(perfis.gravar_perfil(g, destino=self.tmp, forcar=True)[0])

    def test_arquivo_que_nao_e_gguf(self):
        ruim = self.tmp / "modelo.gguf"
        ruim.write_bytes(b"NAOEGGUF" * 10)
        arq, avisos = perfis.gravar_perfil(ruim, destino=self.tmp)
        self.assertTrue(arq.exists())
        self.assertTrue(any("ilegível" in a for a in avisos))

    def test_quant_e_id(self):
        self.assertEqual(perfis._quant("Qwen3.5-4B-UD-Q6_K_XL.gguf"), "UD-Q6_K_XL")
        self.assertEqual(perfis._quant("Bonsai-27B-PQ2_0.gguf"), "PQ2_0")
        self.assertEqual(perfis._quant("modelo-IQ3_XXS.gguf"), "IQ3_XXS")
        self.assertEqual(perfis._id("Qwen3-30B-A3B-Q4_K_M-00001-of-00002.gguf"), "qwen3-30b-a3b-q4-k-m")


class TestSelecao(ComTmp):
    def carregar(self, conteudo=None, **env):
        arq = self.tmp / "selecao.toml"
        if conteudo is not None:
            arq.write_text(conteudo)
        with ambiente(PROVA_SELECAO=arq, **env):
            return selecao.carregar()

    def test_padrao_e_completa_com_tudo(self):
        s = self.carregar()
        self.assertEqual(s["nome"], "completa")
        self.assertEqual(s["etapas"], list(selecao.ETAPAS))
        self.assertEqual(len(s["suites"]), 6)

    def test_todos_os_presets_sao_validos(self):
        for nome in selecao.rodadas():
            with self.subTest(nome):
                s = self.carregar(PROVA_RODADA=nome)
                self.assertTrue(s["etapas"])
                self.assertTrue(selecao.rodadas()[nome].get("descricao"))

    def test_rapida_nao_precisa_de_juiz(self):
        from prova.suites import todas
        s = self.carregar(PROVA_RODADA="rapida")
        juiz = [c for su in todas(s["suites"]) for c in selecao.filtrar(su["casos"], s) if c["avaliacao"] == "juiz"]
        self.assertEqual(juiz, [])

    def test_arquivo_sobrescreve_preset(self):
        s = self.carregar('rodada = "rapida"\nsuites = ["codigo"]\nexcluir = ["codigo.lru-*"]\n')
        self.assertEqual(s["nome"], "rapida (ajustada)")
        self.assertEqual(s["suites"], ["codigo"])
        self.assertFalse(selecao.aceita({"id": "codigo.lru-cache", "dificuldade": "medio"}, s))
        self.assertTrue(selecao.aceita({"id": "codigo.rle", "dificuldade": "medio"}, s))

    def test_ambiente_vence_arquivo(self):
        s = self.carregar('rodada = "codigo"\n', PROVA_RODADA="seguranca")
        self.assertEqual(s["etapas"], ["criticos"])
        s = self.carregar('rodada = "completa"\n', PROVA_SUITES="codigo,raciocinio", PROVA_ETAPAS="suites")
        self.assertEqual((s["suites"], s["etapas"]), (["codigo", "raciocinio"], ["suites"]))

    def test_incluir_e_dificuldades(self):
        s = self.carregar('rodada = "completa"\nincluir = ["agente.*", "codigo.r*"]\ndificuldades = ["dificil"]\n')
        self.assertTrue(selecao.aceita({"id": "codigo.rota-mais-barata", "dificuldade": "dificil"}, s))
        self.assertFalse(selecao.aceita({"id": "codigo.rle", "dificuldade": "medio"}, s))
        self.assertFalse(selecao.aceita({"id": "raciocinio.escada", "dificuldade": "dificil"}, s))
        self.assertEqual(selecao.categorias_esperadas(s), ["codigo", "agente", "contexto"])

    def test_erros_claros(self):
        for conteudo, trecho in (('rodada = "nao-existe"', "não existe"), ('suites = ["xyz"]', "suíte"),
                                 ('etapas = ["voar"]', "etapa"), ('dificuldades = ["moleza"]', "dificuldade")):
            with self.subTest(conteudo):
                with self.assertRaisesRegex(selecao.SelecaoInvalida, trecho):
                    self.carregar(conteudo)

    def test_gravar_e_ler_de_volta(self):
        arq = selecao.gravar("codigo", {"suites": ["codigo", "ferramentas"], "repeticoes_criticos": 3,
                                        "ignorado": 1}, self.tmp / "s.toml")
        with ambiente(PROVA_SELECAO=arq):
            s = selecao.carregar()
        self.assertEqual((s["suites"], s["repeticoes_criticos"]), (["codigo", "ferramentas"], 3))
        self.assertNotIn("ignorado", arq.read_text())


if __name__ == "__main__":
    unittest.main()
