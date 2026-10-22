# Prova9060

Benchmark de modelos locais (GGUF via `llama-server`) feito para uma **AMD Radeon RX 9060 XT 16 GB**,
operado por um agente de IA, um modelo por vez, com placar estilo **ENEM** e parecer escrito pelo agente.

- **~32 min por modelo** a ~30 tok/s na rodada completa: 119 casos, 8 cenários agênticos, contexto longo,
  velocidade, consistência e repetição dos casos críticos. Rodadas menores para triagem.
- **Você escolhe o que roda**: presets (`completa`, `rapida`, `sem-juiz`, `codigo`, `seguranca`,
  `velocidade`) e ajuste por suíte, etapa, dificuldade ou id de caso.
- **Sandbox com bubblewrap** para o código gerado pelo modelo: sem rede, sem acesso ao seu `$HOME`.
- **Só a biblioteca padrão do Python (≥ 3.11).** Nada de `pip install`.
- **Retomável** e **à prova de erro de servidor**: HTTP 500 ou timeout não vira nota zero; o caso é refeito.
- **Problemas originais e dados sintéticos** (nada de HumanEval/MMLU) para reduzir contaminação.
- **142 testes automatizados** offline + CI no GitHub Actions (Python 3.11–3.13).

## Instalação

```bash
git clone https://github.com/cleiton1231/CLaude_bench.git && cd CLaude_bench
sudo dnf install bubblewrap        # Fedora (Arch: pacman -S bubblewrap · Ubuntu: apt install bubblewrap)
scripts/instalar.sh                # guiado: acha o llama-server, cria perfis dos seus GGUF, escolhe a rodada
```

O instalador:
1. confere Python ≥ 3.11, curl e bubblewrap (e diz o comando de instalação da sua distro);
2. procura o `llama-server` (PATH, `~/llama.cpp/build*/bin`, `~/Projetos/llama.cpp/...`) e confere `--jinja`;
3. grava `config/local.toml` (sua máquina, fora do git; `config/hardware.toml` fica intacto);
4. cria um perfil por GGUF numa pasta: lê o cabeçalho do arquivo (camadas, cabeças KV, contexto máximo) e
   calcula o maior `ctx` que cabe nos 16 GB com KV q8_0;
5. pergunta a rodada;
6. roda os testes offline e um ensaio completo com servidor falso.

Para o agente: `scripts/instalar.sh --auto [--bin CAMINHO] [--modelos PASTA] [--rodada NOME]` não pergunta nada.
Perfil avulso: `python3 -m prova novo-perfil ~/modelos/qualquer.gguf`.

## Escolhendo os testes

```bash
scripts/escolher.sh                          # menu
scripts/escolher.sh rapida                   # direto
scripts/escolher.sh completa --suites codigo,ferramentas
python3 -m prova rodada                      # mostra o que está valendo
python3 -m prova estimar config/modelos/<perfil>.toml   # tempo estimado da seleção
```

| Rodada | O que roda | Tempo (30 tok/s) | Juiz? |
|---|---|---:|---|
| `completa` | tudo | ~32 min | sim |
| `sem-juiz` | tudo menos ceticismo e redação (100% reprodutível) | ~30 min | não |
| `rapida` | código, raciocínio, instruções, ferramentas, agente | ~19 min | não |
| `codigo` | código + agente + velocidade | ~12 min | não |
| `seguranca` | só os casos críticos, repetidos 8× | ~12 min | não |
| `velocidade` | prefill/geração/VRAM + contexto longo | ~6 min | não |

A escolha fica em `config/selecao.toml` (modelo em `config/selecao.exemplo.toml`). Dá para sobrescrever
qualquer campo do preset:

```toml
rodada = "completa"
suites = ["codigo", "raciocinio", "ferramentas"]   # ou "todas"
etapas = ["desempenho", "suites", "agente"]       # desempenho suites agente contexto consistencia criticos
dificuldades = ["facil", "medio", "dificil"]
incluir = ["codigo.*", "agente.*"]                # globs de id; vazio = todos
excluir = ["redacao.local-vs-nuvem"]
repeticoes_criticos = 4
```

Por execução, sem mexer no arquivo: `PROVA_RODADA=rapida`, `PROVA_SUITES=codigo`, `PROVA_ETAPAS=suites,agente`.
Os scripts pulam sozinhos as etapas fora da seleção, e o placar só considera o que foi selecionado.

## Rodando

```bash
scripts/00_preflight.sh config/modelos/<perfil>.toml    # ambiente + sandbox + estimativa
scripts/piloto.sh                                       # executa tudo o que é mecânico, sozinho
```

Sem agente, `scripts/rodar_modelo.sh config/modelos/<id>.toml` roda tudo menos o julgamento.

## Automação: o agente sabe sozinho o que fazer

Abra o repositório no OpenCode, Codex ou Claude Code e peça “rode a série”. O `AGENTS.md` (o `CLAUDE.md`
importa) é carregado automaticamente e manda o agente começar por:

```bash
python3 -m prova proximo         # próximo passo exato, deduzido do estado real (ou --json para máquina)
scripts/piloto.sh                # faz sozinho todo o trabalho mecânico de todos os modelos
```

O `proximo` olha configuração, perfis, resultados, servidor, notas e parecer, e responde uma ação: `rodar`
(com o comando), `julgar`, `parecer`, `corrigir` (o agente escreveu um arquivo fora do formato),
`aguardar`, `bloqueado`, `configurar` ou `fim`, sempre com o motivo e o que conferir depois. Não guarda
estado próprio, então funciona depois de qualquer interrupção.

O piloto executa as ações `rodar` em sequência e para com um código de saída que o agente entende:
0 série concluída · 10 sua vez (julgar/parecer/corrigir) · 20 avisar o humano · 1 comando falhou duas vezes.
A ordem é pensada para rodar o máximo sem ninguém olhando: primeiro toda a parte de GPU de todos os
modelos, depois os pacotes do juiz, os julgamentos, os placares e o comparativo, e por fim os pareceres.

Quais modelos e em que ordem: `config/serie.toml` (modelo em `config/serie.exemplo.toml`).

## Árvore

```
.
├── AGENTS.md                 instruções do agente (lido automaticamente por OpenCode/Codex; CLAUDE.md importa)
├── JULGAMENTO.md             como julgar: escala 0–3, ENEM, leitura do relatório, modelo de parecer
├── config/
│   ├── hardware.toml         padrões do projeto (não edite)
│   ├── local.exemplo.toml    modelo do config/local.toml (sua máquina; criado pelo instalar.sh)
│   ├── selecao.exemplo.toml  modelo do config/selecao.toml (o que rodar; criado pelo escolher.sh)
│   ├── rodadas/*.toml        presets de seleção
│   ├── serie.exemplo.toml    modelo do config/serie.toml (quais modelos, em que ordem)
│   └── modelos/*.toml        um perfil por modelo
├── scripts/                  uma etapa por script — o agente roda um de cada vez
│   ├── proximo.sh · piloto.sh  o que fazer agora / fazer sozinho
│   ├── instalar.sh · escolher.sh · 00_preflight.sh
│   ├── 01_subir_modelo.sh … 07_consistencia.sh, 11_criticos.sh   execução (retomáveis)
│   ├── 08_pacote_juiz.sh · 09_pontuar.sh · 10_parar_modelo.sh · 99_comparar.sh
│   ├── rodar_modelo.sh       atalho com todas as etapas da seleção
│   ├── em_fundo.sh / status.sh   etapas longas em segundo plano
│   ├── sensores_gpu.sh       CSV de VRAM/temperatura/potência (sysfs amdgpu)
│   └── ensaio_sem_gpu.sh     pipeline inteiro contra servidor falso
├── suites/
│   ├── 01_codigo.toml        23 · Python com testes ocultos, rodado na sandbox
│   ├── 02_raciocinio.toml    31 · contas, lógica, datas, probabilidade, combinatória
│   ├── 03_instrucoes.toml    20 · formato e restrições (inclui checks por predicado)
│   ├── 04_ceticismo.toml     15 · premissa falsa, bajulação, fonte inventada, controles   [juiz]
│   ├── 05_ferramentas.toml   20 · function calling, encadeamento, erro, conflito, injeção
│   ├── 06_redacao.toml       10 · explicar, resumir com fidelidade, revisar, extrair      [juiz]
│   └── agente/*.toml          8 · corrigir, implementar (com testes ocultos), investigar log,
│                                  injeção no repositório, proteger segredos
├── prova/                    código (cliente, verificadores, sandbox, executor, seleção, pontuação…)
├── tests/                    testes offline, servidor e llama-server falsos, GGUF sintético
└── resultados/<id>/          tudo que uma rodada produz (ver AGENTS.md)
```

## O que é medido

| Categoria | Peso | Como é corrigido |
|---|---:|---|
| código | 20 | código roda na sandbox contra testes ocultos (tudo ou nada) |
| raciocínio | 15 | linha `RESPOSTA:` comparada com o valor exato (tolerância numérica) |
| ferramentas | 13 | nome e argumentos das tool calls, com resultados simulados |
| instruções | 12 | checks de formato e predicados em Python (ordem, acróstico, JSON coerente…) |
| ceticismo | 12 | juiz (0–3) com gabarito + sinais automáticos |
| agente | 10 | testes do projeto virtual (visíveis e ocultos), arquivos protegidos, shell, vazamento de segredo |
| contexto | 10 | código/contagem exatos em fichas sintéticas de 4k até o ctx do perfil |
| redação | 8 | juiz (0–3) com gabarito |

Velocidade, VRAM, consistência e repetição dos críticos **não** entram na nota: são eixos separados.

**ENEM:** fácil vale +1 no acerto e −4 no erro; médio ±2; difícil +3 / −0,5; crítico perde o dobro.
Detalhes e justificativa em `JULGAMENTO.md` §4.

## Sandbox

O código que o modelo escreve (casos de código, testes dos cenários de agente, predicados) roda isolado:

| Nível | Rede | Seus arquivos | Quando |
|---|---|---|---|
| `bwrap` | bloqueada | invisíveis; sistema somente-leitura | bubblewrap instalado e funcionando (recomendado) |
| `unshare` | bloqueada | **visíveis e graváveis** | sem bubblewrap, com namespaces de usuário |
| `basico` | liberada | **visíveis e graváveis** | último recurso |

Em todos: diretório temporário próprio, ambiente limpo (suas variáveis não vazam), stdin fechado, limite de
1 GB de RAM, 20 s de CPU e 16 MB por arquivo. `python3 -m prova sandbox` mostra o nível e, se o bwrap falhar,
o motivo (ex.: Ubuntu 24.04 bloqueia namespaces via AppArmor). Para recusar rodar sem bwrap:
`exigir_isolamento = true` em `[sandbox]` do `config/local.toml`.

## O que cabe em 16 GB (referência)

| Modelo | Quant | Pesos | Observação |
|---|---|---:|---|
| 4–9B | Q6–Q8 | 4–10 GB | sobra para ctx 32k |
| 12–14B | Q4_K_M / Q5_K_M | 8–10,5 GB | ponto ideal; ctx 16–32k com KV q8_0 |
| 20–24B | Q4_K_M | 12–14,5 GB | ctx 8–16k com KV q8_0; fique de olho no transbordo |
| 27–32B denso | IQ3_XXS–Q3_K_M ou ternário | 8–15 GB | quantização agressiva pesa na qualidade |
| MoE 30B-A3B | Q4_K_M | ~18 GB | não cabe inteiro: `args_extra = ["--n-cpu-moe", "N"]` |

`python3 -m prova novo-perfil` faz essa conta pelo cabeçalho do GGUF. O `01_subir_modelo.sh` avisa se a
VRAM passar de ~15,6 GiB (risco de transbordar para a RAM).

## Testes

```bash
python3 -m unittest -v          # ~45 s, offline, sem GPU
```

O que é testado:
- **gabaritos**: todo caso automático aprova uma resposta correta e reprova uma inútil; os 31 gabaritos de
  raciocínio são recalculados em Python; as 23 referências de código passam nos testes e um stub falha;
  cada cenário de agente reprova se nada for feito e aprova com a referência;
- **verificadores**: cada tipo de check nos dois sentidos, extração de números/código/resposta;
- **sandbox**: em cada nível disponível, tenta ler e gravar no repositório, abrir rede, ver variáveis do
  usuário, estourar memória e tempo;
- **execução**: cliente (raciocínio, tool calls, retentativa em HTTP 500), executor (multi-turno, ferramentas
  simuladas, retomada, refazer só o que falhou), loop de agente roteirizado;
- **contexto, perfis, seleção e pontuação**: geração determinística, leitura de GGUF sintético, presets,
  ENEM, critérios de crítico/completo;
- **automação**: cada decisão do `proximo` (sem perfis, servidor de outro modelo, sanidade falha, notas e
  parecer inválidos, piloto rodando) e uma série inteira de dois modelos com um agente simulado julgando;
- **scripts**: `bash -n`, shellcheck, instalador, preflight e o ciclo 01→02→04→09→10 com um llama-server falso
  (inclusive que o 10 não derruba um llama-server seu em outra porta).

Nenhum teste lê seu `config/local.toml`/`selecao.toml` nem grava em `resultados/`.

## Adicionando casos

Cada caso é um bloco `[[caso]]` em TOML com `id`, `dificuldade`, `prompt` e `checks` (automático) ou
`avaliacao = "juiz"` + `gabarito`. Casos automáticos precisam de um jeito de provar o verificador:
`referencia` (código), `exemplo_bom` (texto e/ou chamadas de ferramenta) ou `esperado` direto. Os testes
recusam caso sem isso. Mudar um caso muda o hash dele e só ele é refeito na próxima rodada.

## Limites conhecidos

- O bwrap é forte contra acesso a arquivos e rede, mas não é uma VM: um bug de kernel ainda seria um risco.
  Sem bwrap, o isolamento é fraco: rode como um usuário que você aceite arriscar.
- ~120 casos dão um sinal bom, não uma medida exata: diferenças pequenas são ruído (`JULGAMENTO.md` §7).
- Ceticismo e redação dependem do agente-juiz. Use sempre o mesmo agente na série.
- A estimativa de tempo foi calibrada com uma rodada real (Qwen3.5 4B); modelos prolixos demoram mais.
