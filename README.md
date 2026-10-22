# Prova9060

Benchmark de modelos locais (GGUF via `llama-server`) feito para uma **AMD Radeon RX 9060 XT 16 GB**,
operado por um agente de IA, um modelo por vez, com placar estilo **ENEM** e parecer escrito pelo agente.

- **~35 min por modelo** a ~30 tok/s: 100 casos + 4 cenários agênticos + contexto longo + velocidade + consistência.
- **Só biblioteca padrão do Python (≥ 3.11).** Nada de `pip install`.
- **Retomável:** se cair no meio, roda o mesmo script de novo e continua.
- **Problemas originais e dados sintéticos** (nada de HumanEval/MMLU) para reduzir contaminação.

## Início rápido

```bash
# 1. ajuste o caminho do llama-server (Vulkan ou ROCm)
$EDITOR config/hardware.toml
# 2. crie um perfil por GGUF (copie o exemplo)
cp config/modelos/exemplo-qwen3-14b-q4km.toml config/modelos/qwen3-14b-q4km.toml
# 3. confira o ambiente e ensaie sem GPU
scripts/00_preflight.sh config/modelos/qwen3-14b-q4km.toml
scripts/ensaio_sem_gpu.sh && rm -rf resultados/ensaio
# 4. passe AGENTE.md + JULGAMENTO.md para o agente e peça para ele rodar a série
```

Sem agente, `scripts/rodar_modelo.sh config/modelos/<id>.toml` roda tudo menos o julgamento.

## Árvore

```
prova9060/
├── AGENTE.md                 protocolo de execução para o agente (ordem dos scripts, timeouts)
├── JULGAMENTO.md             como julgar: escala 0–3, ENEM, leitura do relatório, modelo de parecer
├── config/
│   ├── hardware.toml         llama-server, porta, GPU, seed, pesos das categorias
│   └── modelos/*.toml        um perfil por modelo (GGUF, ctx, KV, pensamento, flags)
├── scripts/                  uma etapa por script — o agente roda um de cada vez
│   ├── 00_preflight.sh       ambiente + estimativa de tempo
│   ├── 01_subir_modelo.sh    sobe o llama-server, mede carga e VRAM, inicia sensores
│   ├── 02_sanidade.sh        smoke: chat, raciocínio desligado, tool calling, /tokenize
│   ├── 03_desempenho.sh      prefill/geração com prompts de ~512, 4k e ~15k tokens
│   ├── 04_suites.sh          as 6 suítes de qualidade
│   ├── 05_agente.sh          cenários multi-turno com ferramentas
│   ├── 06_contexto.sh        contexto longo sintético
│   ├── 07_consistencia.sh    estabilidade com temperatura 0.7
│   ├── 08_pacote_juiz.sh     pacote para o juiz
│   ├── 09_pontuar.sh         placar ENEM + relatorio.md
│   ├── 10_parar_modelo.sh    derruba o servidor
│   ├── 99_comparar.sh        tabela comparativa entre modelos
│   ├── rodar_modelo.sh       atalho 01→10 (+08, 09)
│   ├── em_fundo.sh / status.sh   etapas longas em segundo plano
│   ├── sensores_gpu.sh       CSV de VRAM/temperatura/potência (sysfs amdgpu)
│   └── ensaio_sem_gpu.sh     pipeline inteiro contra servidor falso
├── suites/
│   ├── 01_codigo.toml        23 · código Python com testes ocultos (sandbox)
│   ├── 02_raciocinio.toml    21 · contas, lógica, datas, probabilidade
│   ├── 03_instrucoes.toml    16 · formato e restrições (estilo IFEval, PT-BR)
│   ├── 04_ceticismo.toml     15 · premissa falsa, bajulação, fonte inventada, controles  [juiz]
│   ├── 05_ferramentas.toml   15 · function calling, encadeamento, injeção via ferramenta
│   ├── 06_redacao.toml       10 · explicar, resumir com fidelidade, revisar, extrair      [juiz]
│   └── agente/*.toml          4 · corrigir bug, implementar feature, investigar, injeção no repo
├── prova/                    código (cliente, verificadores, sandbox, executor, pontuação…)
├── tests/                    testes offline + servidor falso
└── resultados/<id>/          tudo que uma rodada produz (ver AGENTE.md)
```

## O que é medido

| Categoria | Peso | Como é corrigido |
|---|---:|---|
| código | 20 | código roda na sandbox contra testes ocultos (tudo ou nada) |
| raciocínio | 15 | linha `RESPOSTA:` comparada com o valor exato (tolerância numérica) |
| ferramentas | 13 | nome e argumentos das tool calls, com resultados simulados |
| instruções | 12 | checks de formato (linhas, palavras, JSON, início/fim, etc.) |
| ceticismo | 12 | juiz (0–3) com gabarito + sinais automáticos |
| agente | 10 | testes do projeto virtual passam, arquivos protegidos intactos, sem shell perigoso |
| contexto | 10 | código/contagem exatos em fichas sintéticas de 4k até o ctx do perfil |
| redação | 8 | juiz (0–3) com gabarito |

Velocidade, VRAM e consistência **não** entram na nota: são eixos separados no relatório.

**ENEM:** fácil vale +1 no acerto e −4 no erro; médio ±2; difícil +3 / −0,5; crítico perde o dobro.
Detalhes e justificativa em `JULGAMENTO.md` §4.

## Orçamento de tempo

`python3 -m prova estimar [perfil] [--tps 30]` calcula a partir dos tetos de tokens das suítes:
teto ~100k tokens (55 min), típico ~45k (≈25 min de geração) + ~10 min de prefill/velocidade/consistência.
A duração real de cada etapa fica em `meta.json` e no relatório. Com `pensamento = true` cada chamada
ganha 2048 tokens de folga para raciocinar (e os tetos ×1,5): a rodada passa de 1 h — compare modelos com
raciocínio só entre si.

## O que cabe em 16 GB (referência)

| Modelo | Quant | Pesos | Observação |
|---|---|---:|---|
| 7–9B | Q8_0 | 8–10 GB | sobra para ctx 32k |
| 12–14B | Q4_K_M / Q5_K_M | 8–10,5 GB | ponto ideal; ctx 16–32k com KV q8_0 |
| 20–24B | Q4_K_M | 12–14,5 GB | ctx 8–16k com KV q8_0; fique de olho no transbordo |
| 27–32B denso | IQ3_XXS–Q3_K_M | 11–15 GB | quantização agressiva pesa na qualidade |
| MoE 30B-A3B | Q4_K_M | ~18 GB | não cabe inteiro: `args_extra = ["--n-cpu-moe", "N"]` |

O `01_subir_modelo.sh` avisa se a VRAM passar de ~15,6 GiB (risco de transbordar para a RAM).

## Adicionando casos

Cada caso é um bloco `[[caso]]` em TOML com `id`, `dificuldade`, `prompt` e `checks` (automático) ou
`avaliacao = "juiz"` + `gabarito`. Tipos de check em `prova/verificadores.py`. Casos de código têm
`referencia`, validada por `python3 -m unittest`. Mudar um caso muda o hash dele e força só esse caso a
ser refeito na próxima rodada; compare modelos só dentro da mesma versão das suítes.

## Testes

```bash
python3 -m unittest -v      # offline: suítes válidas, referências passam, verificadores, ENEM, pipeline falso
```

## Limites conhecidos

- A sandbox é *best-effort* (rlimits + `unshare -rn` quando disponível). Código gerado roda na sua máquina.
- 100 casos dão um sinal bom, não uma medida exata: diferenças pequenas são ruído (ver `JULGAMENTO.md` §7).
- Ceticismo e redação dependem do agente-juiz. Use sempre o mesmo agente na série.
