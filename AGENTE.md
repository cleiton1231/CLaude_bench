# AGENTE.md — protocolo de execução

Você (agente) opera a prova: roda os scripts, um modelo por vez, depois julga seguindo `JULGAMENTO.md`.
O humano só cria os perfis em `config/modelos/` e decide quais modelos entram na série.

## Regras

- **Um modelo por vez.** Nunca suba dois `llama-server`. Sempre termine com `10_parar_modelo.sh`.
- Rode os scripts **na ordem** e **um por chamada**. Leia a saída de cada um antes do próximo.
- Bind só em `127.0.0.1`. Não mude seeds, pesos, suítes ou verificadores durante uma série.
- Se uma etapa falhar, **pare e reporte** com as últimas linhas do log. Não “conserte” a prova para passar.
- Não apague `resultados/` de outros modelos.

## Antes da série (uma vez)

```bash
scripts/00_preflight.sh config/modelos/<perfil>.toml   # tudo [ok]? senão, reporte ao humano
scripts/ensaio_sem_gpu.sh                              # ensaio com servidor falso (~10 s)
rm -rf resultados/ensaio
```

## Para cada modelo

| # | Comando | Tempo típico | O que conferir |
|---|---|---:|---|
| 01 | `scripts/01_subir_modelo.sh config/modelos/<id>.toml` | 0,5–2 min | “pronto em Ns”; VRAM carregado < 15,5 GiB |
| 02 | `scripts/02_sanidade.sh <id>` | < 1 min | `sanidade OK`. Se FALHOU: pare, rode 10, reporte |
| 03 | `scripts/03_desempenho.sh <id>` | 2–4 min | tok/s plausíveis (geração > 10) |
| 04 | `scripts/04_suites.sh <id>` | 18–25 min | progresso caso a caso; retomável |
| 05 | `scripts/05_agente.sh <id>` | 4–8 min | 4 cenários |
| 06 | `scripts/06_contexto.sh <id>` | 2–6 min | sem erro HTTP de contexto |
| 07 | `scripts/07_consistencia.sh <id>` | 3–5 min | — |
| 10 | `scripts/10_parar_modelo.sh` | — | “servidor parado” |
| 08 | `scripts/08_pacote_juiz.sh <id>` | — | gera o pacote |
| — | **julgar** (ver `JULGAMENTO.md`) → `resultados/<id>/notas_juiz.json` | — | todos os casos com nota |
| 09 | `scripts/09_pontuar.sh <id>` | — | `completo` |
| — | escrever `resultados/<id>/parecer.md` → rodar 09 de novo | — | parecer no relatório |

Depois do último modelo: `scripts/99_comparar.sh` e um resumo final para o humano.

`<id>` é o nome do arquivo do perfil sem `.toml`.

### Etapas longas e timeout da sua ferramenta

Se a sua ferramenta de shell tem timeout menor que a etapa (a 04 passa de 20 min), rode em segundo plano:

```bash
scripts/em_fundo.sh 04_suites.sh <id>
scripts/status.sh <id>        # repita a cada poucos minutos até aparecer "terminou"
```

Todas as etapas de execução são **retomáveis**: se algo morrer no meio, rode de novo o mesmo script e ele
continua de onde parou (casos já respondidos são pulados). `PROVA_REFAZER=1` força refazer 04 ou 05.

### Variáveis úteis

| Variável | Efeito |
|---|---|
| `PROVA_PORTA` / `PROVA_HOST` | sobrescreve o servidor de `config/hardware.toml` |
| `PROVA_SEED` | seed da série (padrão 1234). Use a mesma para todos os modelos comparados |
| `PROVA_REFAZER=1` | refaz suítes/agente do zero |
| `PY` | interpretador Python (padrão `python3`, precisa ≥ 3.11) |

## Arquivos que você produz e lê

```
resultados/<id>/
├── meta.json              perfil, VRAM, tempo de carga, duração de cada etapa
├── desempenho.json        prefill/geração por tamanho de prompt
├── suites/<suite>.jsonl   uma linha por caso: resposta, checks, tokens, tempo
├── agente.jsonl           cenários agênticos: ações, arquivos alterados, checks
├── contexto.jsonl         contexto longo
├── consistencia.json      estabilidade com temperatura 0.7
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
os críticos falhos e quanto tempo cada rodada levou (está em `relatorio.md`). Sem floreio.
