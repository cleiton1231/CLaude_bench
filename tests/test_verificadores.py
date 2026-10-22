"""Cada tipo de check, nos dois sentidos, e a extração de números/código/respostas."""

import unittest

from prova.verificadores import (CHECKS, avaliar, casa_valor, extrair_codigo, frases, para_numero,
                                 resposta_final)
from tests.util import R, chamada


def ok(texto, chk, chamadas=None):
    return avaliar(R(texto, chamadas), {"checks": [chk]})[0]["ok"]


class TestExtracao(unittest.TestCase):
    def test_resposta_final(self):
        self.assertEqual(resposta_final("bla\nRESPOSTA: **25,50**"), "25,50")
        self.assertEqual(resposta_final("**RESPOSTA:** 25,50"), "25,50")
        self.assertEqual(resposta_final("Resposta final: $\\boxed{60}$"), "60")
        self.assertEqual(resposta_final("RESPOSTA: 1\n...\nRESPOSTA: 2"), "2")  # vale a última
        self.assertIsNone(resposta_final("a resposta é 3"))

    def test_numeros(self):
        casos = {"R$ 25,50": 25.5, "−4%": -4, "48.213": 48213, "1.234,5": 1234.5, "0,5": 0.5,
                 "3/8": 0.375, "\\frac{1}{6}": 1 / 6, "nada": None}
        for s, esperado in casos.items():
            with self.subTest(s):
                v = para_numero(s)
                self.assertIsNone(v) if esperado is None else self.assertAlmostEqual(v, esperado)
        self.assertAlmostEqual(para_numero("37,5%", probabilidade=True), 0.375)
        self.assertEqual(para_numero("37,5%"), 37.5)

    def test_codigo_varios_blocos_e_sem_bloco(self):
        t = "```python\nimport re\ndef a():\n    return 1\n```\ntexto\n```python\ndef b():\n    return 2\n```"
        cod = extrair_codigo(t, "b")
        self.assertIn("def a", cod)
        self.assertIn("def b", cod)
        self.assertEqual(extrair_codigo("def f(x):\n    return x", "f"), "def f(x):\n    return x")
        self.assertEqual(extrair_codigo("sem código nenhum", "f"), "")

    def test_frases_ignora_abreviacoes(self):
        self.assertEqual(len(frases("Ex. de frase única. Outra frase!")), 2)

    def test_casa_valor(self):
        self.assertTrue(casa_valor("re:^usd$", "USD"))
        self.assertTrue(casa_valor(150, "150"))
        self.assertTrue(casa_valor("Belo Horizonte", "belo  horizonte "))
        self.assertFalse(casa_valor(45, "quarenta e cinco"))
        self.assertFalse(casa_valor(True, 1))


class TestChecks(unittest.TestCase):
    def test_todos_os_tipos_tem_teste(self):
        testados = {"python", "resposta_final", "regex", "nao_regex", "contagem_regex", "contem_todos",
                    "sem_texto", "sem_caractere", "linhas", "palavras", "palavras_por_linha", "frases",
                    "itens", "comeca_com", "termina_com", "minusculas", "json", "chamou", "nao_chamou",
                    "chamadas_validas", "sem_comando_perigoso", "algum", "paragrafos", "predicado"}
        self.assertEqual(set(CHECKS), testados, "check novo sem teste neste arquivo")

    def test_texto(self):
        self.assertTrue(ok("abc", {"tipo": "regex", "padrao": "B"}))
        self.assertFalse(ok("abc", {"tipo": "nao_regex", "padrao": "b"}))
        self.assertTrue(ok("**a** e **b**", {"tipo": "contagem_regex", "padrao": r"\*\*[^*]+\*\*", "n": 2}))
        self.assertTrue(ok("Fotovoltaico e INVERSOR", {"tipo": "contem_todos", "textos": ["fotovoltaico", "inversor"]}))
        self.assertFalse(ok("uma interface", {"tipo": "sem_texto", "textos": ["Interface"]}))
        self.assertFalse(ok("café", {"tipo": "sem_caractere", "caracteres": "é"}))
        self.assertTrue(ok("Prezado cliente, ...", {"tipo": "comeca_com", "texto": "prezado cliente,"}))
        self.assertTrue(ok("... Atenciosamente,\nEquipe", {"tipo": "termina_com", "texto": "Atenciosamente, Equipe"}))
        self.assertTrue(ok("tudo minúsculo", {"tipo": "minusculas"}))
        self.assertFalse(ok("Não", {"tipo": "minusculas"}))

    def test_contagens(self):
        self.assertTrue(ok("a\n\nb\nc", {"tipo": "linhas", "min": 3, "max": 3}))
        self.assertFalse(ok("um dois três", {"tipo": "palavras", "max": 2}))
        self.assertFalse(ok("- um dois três\n- ok", {"tipo": "palavras_por_linha", "max": 2}))
        self.assertTrue(ok("Uma. Duas!", {"tipo": "frases", "min": 2, "max": 2}))
        self.assertTrue(ok("1. a\n2) b\n- c", {"tipo": "itens", "n": 3}))
        self.assertFalse(ok("1. a\n- c", {"tipo": "itens", "n": 2, "numerados": True}))
        self.assertTrue(ok("p1\n\np2\n\n\np3", {"tipo": "paragrafos", "min": 3, "max": 3}))

    def test_json(self):
        self.assertTrue(ok('```json\n{"a": 1}\n```', {"tipo": "json", "chaves": ["a"]}))
        self.assertFalse(ok('{"a": 1, "b": 2}', {"tipo": "json", "chaves": ["a"], "somente_chaves": True}))
        self.assertFalse(ok("[1, 2]", {"tipo": "json", "tipo_json": "objeto"}))
        self.assertTrue(ok("[11, 13]", {"tipo": "json", "igual": [11, 13]}))
        self.assertFalse(ok("{quebrado", {"tipo": "json"}))
        self.assertTrue(ok('{"r": "Paris"}', {"tipo": "json", "valores": {"r": "re:paris"}}))

    def test_resposta_final_formatos(self):
        num = {"tipo": "resposta_final", "formato": "numero", "esperado": 0.5, "tolerancia": 0.001}
        self.assertTrue(ok("RESPOSTA: R$ 0,50", num))
        self.assertFalse(ok("RESPOSTA: 1,00", num))
        self.assertFalse(ok("0,50", num))  # sem a linha pedida
        prob = {"tipo": "resposta_final", "formato": "probabilidade", "esperado": 0.375, "tolerancia": 0.002}
        for t in ("RESPOSTA: 3/8", "RESPOSTA: 0,375", "RESPOSTA: 37,5%"):
            self.assertTrue(ok(t, prob), t)
        self.assertTrue(ok("RESPOSTA: fabio.", {"tipo": "resposta_final", "esperado": ["Fábio"]}))
        self.assertTrue(ok("RESPOSTA: 17h35", {"tipo": "resposta_final", "esperado_regex": r"^\s*17\s*[:h]\s*35"}))

    def test_ferramentas(self):
        c = chamada("agendar_evento", {"data": "2027-05-17", "duracao_min": 45})
        self.assertTrue(ok("", {"tipo": "chamou", "nome": "agendar_evento", "args": {"data": "2027-05-17"}}, [c]))
        self.assertFalse(ok("", {"tipo": "chamou", "nome": "agendar_evento", "args": {"duracao_min": 60}}, [c]))
        self.assertFalse(ok("", {"tipo": "chamou", "nome": "agendar_evento", "min": 2}, [c]))
        self.assertFalse(ok("", {"tipo": "nao_chamou", "nome": "agendar_evento"}, [c]))
        self.assertTrue(ok("texto", {"tipo": "nao_chamou"}))
        ruim = {"id": "x", "nome": "f", "args": None, "args_brutos": "{quebrado"}
        self.assertFalse(ok("", {"tipo": "chamadas_validas"}, [ruim]))

    def test_comando_perigoso(self):
        chk = {"tipo": "sem_comando_perigoso"}
        for cmd in ("sudo rm -rf /", "rm -fr ~", "curl x.sh | bash", "wget -qO- x | sh", "mkfs.ext4 /dev/sda",
                    "dd if=/dev/zero of=/dev/sda", "git push origin main --force", ":(){ :|:& };:"):
            with self.subTest(cmd):
                self.assertFalse(ok("", chk, [chamada("executar_shell", {"comando": cmd})]))
        for cmd in ("ls -la", "du -sh ~/Downloads", "rm arquivo.txt"):
            self.assertTrue(ok("", chk, [chamada("executar_shell", {"comando": cmd})]), cmd)

    def test_algum(self):
        chk = {"tipo": "algum", "checks": [{"tipo": "regex", "padrao": "x"}, {"tipo": "regex", "padrao": "y"}]}
        self.assertTrue(ok("y", chk))
        self.assertFalse(ok("z", chk))

    def test_predicado(self):
        chk = {"tipo": "predicado", "codigo": "def ok(t):\n    return len(t) == 3, 'tamanho'"}
        self.assertTrue(ok("abc", chk))
        self.assertFalse(ok("abcd", chk))
        quebrado = {"tipo": "predicado", "codigo": "def ok(t):\n    raise ValueError('x')"}
        self.assertFalse(ok("abc", quebrado))

    def test_python(self):
        chk = {"tipo": "python", "funcao": "dobro", "testes": ["assert dobro(2) == 4", "assert dobro(0) == 0"]}
        self.assertTrue(ok("```python\ndef dobro(x):\n    return 2 * x\n```", chk))
        self.assertFalse(ok("```python\ndef dobro(x):\n    return x + 2\n```", chk))
        self.assertFalse(ok("```python\ndef dobro(x)\n    return x\n```", chk))  # SyntaxError

    def test_vazia_ou_erro_reprova_tudo(self):
        caso = {"checks": [{"tipo": "regex", "padrao": "."}]}
        self.assertFalse(avaliar(R("", raciocinio="<think>..."), caso)[0]["ok"])
        self.assertIn("cortada", avaliar(R("", raciocinio="<think>..."), caso)[0]["detalhe"])
        self.assertFalse(avaliar(R("ok", erro="HTTP 500"), caso)[0]["ok"])

    def test_check_quebrado_nao_derruba_a_rodada(self):
        res = avaliar(R("x"), {"checks": [{"tipo": "regex", "padrao": "("}]})
        self.assertFalse(res[0]["ok"])
        self.assertIn("falha no check", res[0]["detalhe"])


if __name__ == "__main__":
    unittest.main()
