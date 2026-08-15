# CVM — Configuration Vulnerability Meter (v2)

**Avaliação multidimensional de risco de configuração: configuração, permissões
e exposição de rede, com score CCSS reproduzível e detecção de cadeias de
ataque.**

---

## O que é este repositório, e o que não é

Este repositório é a **versão 2** da implementação do CVM. Nasceu por fork do
[CASPAR](https://github.com/AFilipe-IT/CASPAR) em 2026-08-13 e herda o seu motor
completo: doze plugins, 514 regras, 32 cadeias de ataque, extracção de
conhecimento por LLM+RAG em build-time, e scoring CCSS determinístico em
runtime.

**O CASPAR não foi arquivado nem substituído.** Continua a ser a implementação de
referência que a dissertação descreve e cujos resultados a tese cita — 20/20 de
concordância com o CCE nas entradas com score publicado, 96/96 de detecção, 746
testes passados. Esse estado está congelado e é auditável ali.

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

**As seis fases do [`PLANO_V2.md`](PLANO_V2.md) estão implementadas e testadas**
(2026-08-14). A suíte está em 1146 testes Python passados e 23 saltados; a
consola v2 passa 23 testes próprios e typecheck limpo.

| Componente | Estado |
|---|---|
| Motor v1 (12 plugins, scoring CCSS, cadeias) | herdado, funcional |
| `plugin fetch` com fonte SSG (Fase 0) | **feito** — ver abaixo |
| Inventário de hosts (Fase A) | **feito** — `core/inventory.py`, `hosts.uuid` persistente |
| Scoring multidimensional (Fase B) | **feito** — `core/engines/dimensions.py::aggregate_posture` |
| Alvo `ubuntu2204` e as três dimensões (Fase C) | **feito** — colectores `permissions.py` e `exposure.py` |
| Consola v2 (`frontend-v2/`) ligada à API real (Fase D) | **feito** — sem dados fictícios |
| Validação medida (Fase E) | **feito** — resultados em [`PLANO_V2.md`](PLANO_V2.md#fase-e--validação) |
| Contrato de API v2 | especificado ([`CONTRATO_API_V2.md`](CONTRATO_API_V2.md)) |

As três ressalvas que acompanham os números da Fase E (a concordância junta pelo
objecto observado e não pelo número de secção; a sensibilidade exige anfitriões
multidimensionais; a frota usada é sintética) estão escritas por extenso no
plano, e pertencem à dissertação — não apenas ao repositório.

### Fase 0 — fonte de benchmarks reposta

O `plugin fetch` dependia do `stigviewer.com`, que passou a exigir autenticação.
Verificado em 2026-08-13: **HTTP 401 em todos os alvos** — as 45 entradas de
`config_assessment/fetch/catalog.json` ficaram inacessíveis.

A fonte foi substituída pelo **SCAP Security Guide** (ComplianceAsCode/content),
que é público, versionado e traz o CIS Ubuntu 22.04 v2.0.0 completo. Os alvos de
sistema operativo passam a ter uma fonte `ssg` antes da `stigviewer`; as fontes
`stigviewer` que restam explicam que fecharam, em vez de falharem genericamente.

Ao contrário de um STIG em prosa, o `rule.yml` do SSG guarda o par
(identificador, valor esperado) de forma estruturada, com override por produto:

```yaml
template:
    name: file_permissions
    vars:
        filepath: /etc/shadow
        filemode: '0000'
        filemode@ubuntu2204: '0640'
```

Isso permite extrair **223 das 400 regras** do CIS Ubuntu 22.04 L1 Server sem
recorrer ao LLM. A proveniência de cada regra fica registada no XCCDF emitido
(`cvm:deterministic`), para que a validação possa separar o que foi derivado do
que foi inferido — as regras inferidas entram no mesmo regime do `apache-httpd`
e precisam do seu próprio MAE.

```bash
caspar plugin fetch ubuntu2204 -o ./benchmarks
```

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

## Arranque rápido

Publicado no PyPI como [`cvm-caspar`](https://pypi.org/project/cvm-caspar/) — o
comando instalado continua a chamar-se `caspar`:

```bash
pip install cvm-caspar
caspar init                                    # uma vez, só em instalações por pip
caspar demo                                    # escreve caspar-demo/
caspar scan caspar-demo/apache-vulnerable.conf # 8.7/10 HIGH, 4 cadeias
```

O `caspar init` existe porque o wheel transporta o dump canónico da base de
conhecimento, não a base construída; restaurá-lo dá as mesmas 514 regras que a
imagem Docker e o instalador do repositório trazem, para que os scores sejam
comparáveis nas três vias. Depois, `caspar scan caspar-demo/apache-hardened.conf`
mostra o score a descer sobre a mesma directiva.

Para a consola web:

```bash
pip install "cvm-caspar[api]"                  # acrescenta o servidor
caspar serve                                   # :2027 → /app, /v1/app, /docs
```

As duas consolas **já vêm instaladas** no `pip install cvm-caspar` — o `dist/`
está versionado e vai dentro do wheel. O extra `[api]` acrescenta o FastAPI e o
uvicorn, ou seja o servidor que as serve, não as consolas.

## Instalação a partir do repositório

Para desenvolver, ou para reproduzir o build. O processo é o do CASPAR e não
mudou — ver [`INSTALL.md`](INSTALL.md).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

A consola v2 consome a API real. Arranque o backend primeiro — o servidor de
desenvolvimento encaminha `/api` para ele, e não existe middleware de CORS por
opção:

```bash
caspar serve                                    # backend em :2027
cd frontend-v2 && npm install && npm run dev    # consola em :5173
```

O servidor de desenvolvimento só é preciso para *editar* a consola. Para a usar
basta o `caspar serve`, que monta **a v2 em `/app`** — é a consola principal — e
a v1 em `/v1/app`, a partir do `dist/` versionado.

A v1 continua disponível porque é o que o artefacto validado entrega e o que as
figuras da dissertação mostram; `/v1/app` é uma morada estável para ela, não uma
depreciação.

O preço de versionar o build é que editar `frontend-v2/src/` (ou `frontend/src/`)
obriga a correr `npm run build` e a commitar o `dist/` resultante — caso
contrário a consola servida continua a ser a anterior. O `base` vem fixado no
`vite.config.ts` de cada uma (`/app/` e `/v1/app/`), pelo que um `npm run build`
normal produz sempre o prefixo certo.

## Licença e proveniência

**Apache 2.0** — ver [LICENSE](LICENSE). O [NOTICE](NOTICE) declara a
proveniência de tudo o que não é código próprio e viaja com as distribuições,
como o §4(d) da licença exige.

O método de scoring implementa o CCSS (NISTIR 7502, NIST — publicação do governo
dos EUA, sem copyright). A base de conhecimento **deriva** de CIS Benchmarks e
DISA STIGs públicos, com proveniência declarada por alvo: o que é distribuído
são regras extraídas com métricas, justificações e remediações próprias, não os
documentos de origem — esses nunca viajam no repositório, nas distribuições nem
nas imagens, e quem constrói um alvo novo fornece o seu. A v2 acrescenta o SCAP
Security Guide (ComplianceAsCode/content, BSD-3-Clause, © Red Hat) como fonte,
fixado por versão e com o SHA registado no manifesto de reprodutibilidade.
