# CVM — Configuration Vulnerability Meter (v2)

**Avaliação multidimensional de risco de configuração: configuração, permissões
e exposição de rede, com score CCSS reproduzível e detecção de cadeias de
ataque.**

---

## O que é este repositório, e o que não é

Este repositório é a **versão 2** da implementação do CVM. Nasceu por fork do
[CASPAR](https://github.com/AFilipe-IT/caspar) em 2026-08-13, no commit
`2d8c4f5`, e herda o seu motor completo: doze plugins, 514 regras, 32 cadeias de
ataque, extracção de conhecimento por LLM+RAG em build-time, scoring CCSS
determinístico em runtime, e 846 testes.

**O CASPAR não foi arquivado nem substituído.** Continua a ser a implementação de
referência que a dissertação descreve e cujos resultados a tese cita — 20/20 de
concordância com o CCE nas entradas com score publicado, 96/96 de detecção, 846
testes. Esse estado está congelado e é auditável ali.

A separação existe precisamente por isso: a v2 altera o modelo de scoring,
estende `core/target.py` e introduz 225 regras ainda por validar. Misturar esse
trabalho com o artefacto validado tornaria impossível responder, na defesa, à
pergunta "o que é que estava validado, e quando?".

| | CASPAR | CVM (este repo) |
|---|---|---|
| Papel | implementação de referência da tese | evolução para produto |
| Estado | congelado, validado | em desenvolvimento |
| Dimensões | configuração | configuração, permissões, exposição |
| Unidade de avaliação | caminho de configuração | host inventariado |
| Indicador global | pior achado individual | agregação por dimensão, parametrizável e versionada |
| Consola | `frontend/` (Vite + CSS Modules) | `frontend-v2/` (TanStack + Tailwind) |

## Estado actual

**Nada da v2 está implementado ainda.** O que existe é o motor herdado do CASPAR,
a documentação de planeamento, e a consola v2 desenhada mas ainda a consumir
dados fictícios.

| Componente | Estado |
|---|---|
| Motor v1 (12 plugins, scoring CCSS, cadeias) | herdado, funcional |
| Consola v2 (`frontend-v2/`) | desenhada, sobre dados fictícios |
| Contrato de API v2 | especificado ([`CONTRATO_API_V2.md`](CONTRATO_API_V2.md)) |
| Inventário de hosts | tabela existe e está vazia; por estender |
| Scoring multidimensional | por implementar |
| Dimensões de permissões e exposição | por implementar |
| `plugin fetch` | **partido** — ver abaixo |

### Regressão conhecida

O `plugin fetch` depende do `stigviewer.com`, que passou a exigir autenticação.
Verificado em 2026-08-13: **HTTP 401 em todos os alvos** — as 45 entradas de
`config_assessment/fetch/catalog.json` estão inacessíveis. A Fase 0 do plano
substitui esta fonte pelo SCAP Security Guide do ComplianceAsCode, que é público
e traz o CIS Ubuntu 22.04 v2.0.0 completo.

## Documentos de planeamento

Leia-os por esta ordem — cada um pressupõe o anterior.

| Documento | O que responde |
|---|---|
| [`PLANO_V2.md`](PLANO_V2.md) | O plano de execução: fases, dependências, custos e riscos. **Começa aqui.** |
| [`CONTRATO_API_V2.md`](CONTRATO_API_V2.md) | As formas exactas de dados que o backend serve e a consola consome |
| [`PRD_v2_seccoes.md`](PRD_v2_seccoes.md) | Secções para o PRD: estado actual, modelo de avaliação, sequenciamento |
| [`PROMPT_LOVABLE.md`](PROMPT_LOVABLE.md) | A especificação que gerou a consola v2, e a iteração que a densificou |

A documentação do motor herdado está em [`docs/`](docs/), numerada pela ordem de
leitura. O README original do CASPAR ficou em
[`docs/01_README_CASPAR_v1.md`](docs/01_README_CASPAR_v1.md) — continua a ser a
referência de comandos válida, porque o CLI não mudou.

## As três dimensões da v2

A v1 avalia ficheiros de configuração. A v2 acrescenta duas dimensões que o
plugin `ubuntu` do CASPAR declara explicitamente como limitação assumida
(*"whole-system state checks are OpenSCAP's domain, out of scope here"*) —
fechá-la é um dos resultados que a v2 procura.

| Dimensão | Identificador | Valor observado | Proveniência |
|---|---|---|---|
| Configuração | `ServerTokens` | `Full` | ficheiro + linha |
| Permissões | `/etc/shadow:mode` | `0644` | inode (`stat`) |
| Exposição | `tcp/0.0.0.0:6379` | `redis-server` | socket + processo |

Três dimensões são avaliadas; **segredos, patch intelligence e platform
hardening são declaradas `not_assessed`** — um estado distinto de "avaliada e
limpa", visível na consola e contabilizado na cobertura. Um sistema onde só se
avaliou uma dimensão não pode apresentar o mesmo indicador que um onde se
avaliaram seis e nada se encontrou.

### Cadeias de ataque

As cadeias continuam a **não entrar no indicador global**, por decisão de
acionabilidade herdada da v1: um score que o operador não consegue rastrear até
uma directiva concreta é um score sobre o qual não pode agir. A v2 dá-lhes um
**indicador de risco combinado próprio**, ao lado do global e não fundido nele.

## Âmbito

Instância única por organização, self-hosted. **Sem multi-tenancy, sem contas de
utilizador, sem serviço alojado.** O CVM corre onde estão os sistemas a avaliar,
que é também o que dispensa agentes e credenciais SSH de terceiros: ler modos de
ficheiros e sockets à escuta é a mesma posição de execução com que já se lêem
ficheiros de configuração.

## Instalação

O processo é o do CASPAR e não mudou — ver [`INSTALL.md`](INSTALL.md).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

A consola v2 ainda não está ligada ao backend; para a ver com os dados
fictícios:

```bash
cd frontend-v2 && npm install && npm run dev
```

## Licença e proveniência

Herda a licença do CASPAR. A base de conhecimento deriva de CIS Benchmarks e
DISA STIGs públicos, com proveniência declarada por alvo. A v2 acrescenta o SCAP
Security Guide (ComplianceAsCode/content) como fonte, fixado por versão e com o
SHA registado no manifesto de reprodutibilidade.
