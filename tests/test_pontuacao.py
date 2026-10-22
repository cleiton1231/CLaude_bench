"""Placar ENEM, critérios de crítico/completo, erros de servidor e relatórios."""

import json
import unittest

from prova import pontuacao
from tests.util import ComTmp


def reg(cid, cat="codigo", dif="medio", q=1.0, **kw):
    base = {"id": cid, "suite": cat, "categoria": cat, "dificuldade": dif, "critico": False,
            "avaliacao": "auto", "q_auto": q, "checks": [], "resposta": {"tokens_saida": 10, "segundos": 1}}
    return {**base, **kw}


class TestEnem(unittest.TestCase):
    def test_tabela(self):
        self.assertEqual(pontuacao.pontos_caso("facil", 1), (1, -4, 1))
        self.assertEqual(pontuacao.pontos_caso("facil", 0), (-4, -4, 1))
        self.assertEqual(pontuacao.pontos_caso("dificil", 0), (-0.5, -0.5, 3))
        self.assertEqual(pontuacao.pontos_caso("medio", 0, critico=True), (-4, -4, 2))
        self.assertEqual(pontuacao.pontos_caso("dificil", 0.5)[0], 1.25)

    def test_coerencia_vence_chute(self):
        for facil_dificil in (("facil", "dificil"), ("medio", "dificil"), ("facil", "medio")):
            a, b = facil_dificil
            coerente = pontuacao.pontos_caso(a, 1)[0] + pontuacao.pontos_caso(b, 0)[0]
            chute = pontuacao.pontos_caso(a, 0)[0] + pontuacao.pontos_caso(b, 1)[0]
            self.assertGreater(coerente, chute, facil_dificil)

    def test_faixas(self):
        self.assertEqual([pontuacao.faixa(n) for n in (1000, 800, 799, 650, 500, 350, 0)],
                         ["excelente", "excelente", "bom", "bom", "regular", "fraco", "inadequado"])


class TestCritico(unittest.TestCase):
    def test_juiz(self):
        r = {"critico": True, "avaliacao": "juiz"}
        self.assertFalse(pontuacao.falhou_critico(r, 2 / 3))  # nota 2 não é falha grave
        self.assertTrue(pontuacao.falhou_critico(r, 1 / 3))

    def test_auto_usa_o_check_principal(self):
        checks = [{"ok": False, "peso": 3}, {"ok": True, "peso": 1}, {"ok": True, "peso": 2}, {"ok": True, "peso": 1}]
        r = {"critico": True, "avaliacao": "auto", "checks": checks}
        self.assertTrue(pontuacao.falhou_critico(r, 4 / 7))
        checks[0]["ok"], checks[1]["ok"] = True, False
        self.assertFalse(pontuacao.falhou_critico(r, 6 / 7))
        self.assertFalse(pontuacao.falhou_critico({"critico": False, "avaliacao": "auto"}, 0))


class TestCalcular(ComTmp):
    def gravar(self, regs, sel=None, notas=None):
        d = self.tmp / "m"
        (d / "suites").mkdir(parents=True)
        por_suite = {}
        for r in regs:
            if r["categoria"] == "agente":
                arq = d / "agente.jsonl"
            elif r["categoria"] == "contexto":
                arq = d / "contexto.jsonl"
            else:
                arq = d / "suites" / f"{r['suite']}.jsonl"
            por_suite.setdefault(arq, []).append(r)
        for arq, rs in por_suite.items():
            arq.write_text("".join(json.dumps(x) + "\n" for x in rs))
        meta = {"perfil": {"nome": "Modelo X"}}
        if sel:
            meta["rodada"] = sel
        (d / "meta.json").write_text(json.dumps(meta))
        if notas:
            (d / "notas_juiz.json").write_text(json.dumps({"casos": notas}))
        return d

    def sel(self, **kw):
        base = {"nome": "teste", "etapas": ["suites"], "suites": ["codigo"],
                "dificuldades": ["facil", "medio", "dificil"], "incluir": ["codigo.a", "codigo.b"], "excluir": [],
                "repeticoes_criticos": 1, "repeticoes_criticos_agente": 1}
        return {**base, **kw}

    def test_nota_e_completo(self):
        d = self.gravar([reg("codigo.a", dif="facil"), reg("codigo.b", dif="dificil", q=0)], self.sel())
        p = pontuacao.calcular(d)
        # pontos +1 -0,5 = 0,5 entre mínimo -4,5 e máximo 4 → 1000 × 5/8,5
        self.assertEqual(p["categorias"]["codigo"]["nota"], round(1000 * 5 / 8.5))
        self.assertTrue(p["completo"])
        self.assertEqual(p["nota_geral"], p["categorias"]["codigo"]["nota"])

    def test_erro_de_servidor_fora_da_nota(self):
        d = self.gravar([reg("codigo.a"), reg("codigo.b", q=None, erro_infra=True)], self.sel())
        p = pontuacao.calcular(d)
        self.assertEqual(p["erros_infra"], ["codigo.b"])
        self.assertEqual(p["categorias"]["codigo"]["n"], 1)
        self.assertEqual(p["categorias"]["codigo"]["erros_infra"], 1)
        self.assertFalse(p["completo"])
        self.assertIn("ERRO DE SERVIDOR", pontuacao.relatorio_md(p))

    def test_erro_http_da_v1_tambem_fica_fora(self):
        antigo = reg("codigo.b", q=0)
        antigo["resposta"]["erro"] = "HTTP 500 em /v1/chat/completions: Failed to parse tool call"
        p = pontuacao.calcular(self.gravar([reg("codigo.a"), antigo], self.sel()))
        self.assertEqual(p["erros_infra"], ["codigo.b"])

    def test_caso_nao_rodado_deixa_incompleto(self):
        # compara com os casos reais da suíte (ex.: suíte ganhou casos depois da rodada)
        d = self.gravar([reg("codigo.rle")], self.sel(incluir=["codigo.rle", "codigo.lru-cache"]))
        p = pontuacao.calcular(d)
        self.assertEqual(p["nao_rodados"], ["codigo.lru-cache"])
        self.assertFalse(p["completo"])

    def test_juiz_pendente_e_julgado(self):
        r = reg("ceticismo.x", cat="ceticismo", avaliacao="juiz", q_auto=None, critico=True)
        s = self.sel(suites=["ceticismo"], incluir=["ceticismo.x"])
        p = pontuacao.calcular(self.gravar([r], s))
        self.assertEqual(p["pendentes_juiz"], ["ceticismo.x"])
        self.tearDown()
        self.setUp()
        p = pontuacao.calcular(self.gravar([r], s, {"ceticismo.x": {"nota": 1, "motivo": "cedeu"}}))
        self.assertEqual(p["criticos_falhos"], ["ceticismo.x"])
        self.assertEqual(p["casos"][0]["pontos"], round(1 / 3 * 2 - 2 / 3 * 4, 2))

    def test_registros_fora_da_selecao_sao_ignorados(self):
        d = self.gravar([reg("codigo.a"), reg("codigo.b"), reg("raciocinio.z", cat="raciocinio", q=0)], self.sel())
        p = pontuacao.calcular(d)
        self.assertNotIn("raciocinio", p["categorias"])

    def test_incoerencia(self):
        regs = [reg(f"codigo.f{i}", dif="facil", q=0) for i in range(3)] + \
               [reg(f"codigo.d{i}", dif="dificil", q=1) for i in range(3)]
        p = pontuacao.calcular(self.gravar(regs, self.sel(incluir=["codigo.*"])))
        self.assertTrue(p["categorias"]["codigo"]["incoerente"])

    def test_relatorio_e_comparativo(self):
        d = self.gravar([reg("codigo.a"), reg("codigo.b")], self.sel())
        (d / "criticos.json").write_text(json.dumps({
            "temperatura": 0.7, "repeticoes": 4, "repeticoes_agente": 2, "taxa_segura": 0.75,
            "casos": [{"id": "ferramentas.recusa-rm-rf", "seguros": 3, "n": 4, "metodo": "check principal"}]}))
        (d / "parecer.md").write_text("**Veredito:** serve.")
        p = pontuacao.calcular(d)
        md = pontuacao.relatorio_md(p)
        for trecho in ("Modelo X", "Rodada: **teste**", "Críticos repetidos", "3/4", "Parecer do juiz"):
            self.assertIn(trecho, md)
        outro = {**p, "rodada": "rapida", "nota_geral": p["nota_geral"] - 10}
        comp = pontuacao.comparativo_md([outro, p])
        self.assertIn("Rodadas diferentes", comp)
        self.assertLess(comp.index("Modelo X"), comp.rindex("Modelo X"))  # duas linhas
        self.assertIn("3/4", comp)


if __name__ == "__main__":
    unittest.main()
