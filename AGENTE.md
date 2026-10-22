# AGENTE.md — protocolo de execução

Você (agente) opera a prova: roda os scripts, um modelo por vez, depois julga seguindo `JULGAMENTO.md`.
O humano cria os perfis em `config/modelos/`, escolhe a rodada e decide quais modelos entram na série.

## Regras

- **Um modelo por vez.** Nunca suba dois `llama-server`. Sempre termine com `10_parar_modelo.sh`.
- Rode os scripts **na ordem** e **um por chamada**. Leia a saída de cada um antes do próximo.
- Bind só em `127.0.0.1`. Não mude seeds, pesos, suítes, verificadores ou a rodada no meio de uma série.
- Se uma etapa falhar, **pare e reporte** com as últimas linhas do log. Não “conserte” a prova para passar.
- Não apague `resultados/` de outros modelos.

## Antes da série (uma vez)

```bash
scripts/instalar.sh --auto                             # ou sem --auto, se o humano estiver junto
python3 -m prova rodada                                # confira a rodada escolhida e as categorias
scripts/00_preflight.sh config/modelos/<perfil>.toml   # tudo [ok]? senão, reporte ao humano
```

`instalar.sh` já roda os testes offline e o ensaio com servidor falso. Se o preflight mostrar
`sandbox fraca`, avise o humano antes de seguir: o código gerado pelos modelos vai rodar sem isolamento de
arquivos (veja `python3 -m prova sandbox`).

### Escolher o que rodar

A rodada fica em `config/selecao.toml` (`scripts/escolher.sh` cria). Presets em `config/rodadas/`:

| Rodada | O que roda | Tempo (30 tok/s) | Juiz? |
|---|---|---:|---|
| `completa` | tudo | ~32 min | sim |
| `sem-juiz` | tudo menos ceticismo e redação | ~30 min | não |
| `rapida` | código, raciocínio, instruções, ferramentas, agente | ~19 min | não |
| `codigo` | código + agente + velocidade | ~12 min | não |
| `seguranca` | só os críticos, repetidos 8× | ~12 min | não |
| `velocidade` | só velocidade e contexto | ~6 min | não |

Etapas fora da rodada são puladas sozinhas (o script imprime “desligada na rodada”). Compare modelos
**só dentro da mesma rodada**: o comparativo avisa quando elas diferem.

## Para cada modelo

| # | Comando | Tempo típico | O que conferir |
|---|---|---:|---|
| 01 | `scripts/01_subir_modelo.sh config/modelos/<id>.toml` | 0,5–2 min | “pronto em Ns”; VRAM carregado < 15,5 GiB |
| 02 | `scripts/02_sanidade.sh <id>` | < 1 min | `sanidade OK`. Se FALHOU: pare, rode 10, reporte. Leia os AVISOS |
| 03 | `scripts/03_desempenho.sh <id>` | 2 min | tok/s plausíveis (geração > 10) |
| 04 | `scripts/04_suites.sh <id>` | 10–15 min | progresso caso a caso; `INFRA` = erro do servidor |
| 05 | `scripts/05_agente.sh <id>` | 5–7 min | 8 cenários |
| 06 | `scripts/06_contexto.sh <id>` | 2–4 min | sem `INFRA` |
| 07 | `scripts/07_consistencia.sh <id>` | 3–4 min | — |
| 11 | `scripts/11_criticos.sh <id>` | 4–6 min | “seguro k/N” por caso |
| 10 | `scripts/10_parar_modelo.sh` | — | “servidor parado” |
| 08 | `scripts/08_pacote_juiz.sh <id>` | — | gera o pacote (se a rodada tem casos de juiz) |
| — | **julgar** (ver `JULGAMENTO.md`) → `resultados/<id>/notas_juiz.json` | — | todos os casos com nota |
| 09 | `scripts/09_pontuar.sh <id>` | — | `completo` |
| — | escrever `resultados/<id>/parecer.md` → rodar 09 de novo | — | parecer no relatório |

Depois do último modelo: `scripts/99_comparar.sh` e um resumo final para o humano.
`scripts/rodar_modelo.sh config/modelos/<id>.toml` faz 01→11 + 08 + 09 de uma vez, se preferir.

`<id>` é o nome do arquivo do perfil sem `.toml`.

### Erros de servidor (`INFRA`)

HTTP 500, timeout ou queda do servidor **não** são culpa do modelo: o caso fica fora da nota, o placar sai
`INCOMPLETO` e o relatório lista os casos. Típico: template de tool calling quebrado (o 02 avisa). Corrija
(llama.cpp mais novo, `--chat-template-file` em `args_extra`) e rode **a mesma etapa de novo**: só os
casos com erro são refeitos.

### Etapas longas e timeout da sua ferramenta

Se a sua ferramenta de shell tem timeout menor que a etapa, rode em segundo plano:

```bash
scripts/em_fundo.sh 04_suites.sh <id>
scripts/status.sh <id>        # repita a cada poucos minutos até aparecer "terminou"
```

Todas as etapas de execução são **retomáveis**: se algo morrer no meio, rode de novo o mesmo script e ele
continua de onde parou. Casos alterados nas suítes (hash diferente) e casos novos são executados; o resto é
reaproveitado. `PROVA_REFAZER=1` força refazer 04 ou 05.

### Variáveis úteis

| Variável | Efeito |
|---|---|
| `PROVA_RODADA=<nome>` | usa um preset sem mexer em `config/selecao.toml` |
| `PROVA_SUITES=codigo,raciocinio` / `PROVA_ETAPAS=suites,agente` | ajuste pontual da seleção |
| `PROVA_PORTA` / `PROVA_HOST` | sobrescreve o servidor |
| `PROVA_SEED` | seed da série (padrão 1234). Use a mesma para todos os modelos comparados |
| `PROVA_REFAZER=1` | refaz suítes/agente do zero |
| `PROVA_SANDBOX=bwrap` | força um nível de sandbox (falha se indisponível) |
| `PY` | interpretador Python (padrão `python3`, precisa ≥ 3.11) |

## Arquivos que você produz e lê

```
resultados/<id>/
├── meta.json              perfil, VRAM, tempo de carga, rodada, nível da sandbox, duração de cada etapa
├── desempenho.json        prefill/geração por tamanho de prompt
├── suites/<suite>.jsonl   uma linha por caso: resposta, checks, tokens, tempo, erro_infra
├── agente.jsonl           cenários agênticos: ações, arquivos alterados, checks
├── contexto.jsonl         contexto longo
├── consistencia.json      estabilidade com temperatura 0.7
├── criticos.json          repetição dos casos críticos: seguro k/N
├── sensores.csv           VRAM/temperatura/potência a cada 5 s
├── logs/                  llama-server.log e logs das etapas em fundo
├── pacote_juiz.md         ← você lê
├── notas_juiz.json        ← você escreve
├── parecer.md             ← você escreve
├── placar.json            gerado pelo 09
└── relatorio.md           gerado pelo 09
```

## Resumo final para o humano

Ao terminar a série, entregue: a tabela de `resultados/comparativo.md`, uma linha de veredito por modelo,
os críticos falhos **com o “seguro k/N” das repetições**, erros de servidor que sobraram e quanto tempo cada
rodada levou (está em `relatorio.md`). Sem floreio.
