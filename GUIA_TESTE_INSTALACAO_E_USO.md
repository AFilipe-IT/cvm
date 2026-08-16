# Guia de teste — modos de instalação e cobertura de comandos

Guia de execução manual numa máquina de teste. Cobre as **quatro vias de
instalação** e os **23 comandos** do CLI, mais as duas consolas web e a API REST.

Cada passo traz o que se espera ver. Um passo falha quando o observado difere do
esperado — não quando o comando devolve texto que não se reconhece.

Verificado contra `caspar 1.1.1` a 2026-08-16.

> **Números desta árvore.** O working DB da v2 tem **12 alvos / 514 regras**,
> digest `kb sha256:f595efe56da0`. Não confundir com os **11 alvos / 488 regras**
> (`sha256:37087229989b`) da base canónica da dissertação: a diferença é o
> `postgresql` (26 regras) construído localmente. Os dois valores estão certos —
> o que importa é que **um digest diferente do esperado invalida a comparação de
> scores**, não que um número seja melhor que o outro.

---

## 0a. Script — as três vias na mesma máquina

Testar mais do que uma via na mesma máquina só é fiável com isolamento. O
[`scripts/test-install-modes.sh`](scripts/test-install-modes.sh) dá a cada via o
seu venv, a sua base de dados e o seu porto, e limpa tudo a um comando.

```bash
./scripts/test-install-modes.sh doctor   # comece aqui: Python, docker, disco, bundles
./scripts/test-install-modes.sh pypi     # via A
./scripts/test-install-modes.sh repo     # via B (corre a suite)
./scripts/test-install-modes.sh docker   # via C
./scripts/test-install-modes.sh all      # as três em sequência
./scripts/test-install-modes.sh status   # o que está instalado/a correr
./scripts/test-install-modes.sh clean    # apaga tudo o que o script criou
```

Cada via verifica score 8.7, digest `f595efe56da0`, 12 alvos, o código de saída
do `--threshold`, e as duas consolas mais o Swagger. Tudo vive em `~/.cvm-test`
(mude com `CVM_TEST_BASE`); o `clean` remove só isso — o repositório e a `ccss.db`
de trabalho não são tocados, e as imagens Docker ficam.

**Se uma consola der 404**, o script imprime automaticamente *onde* o `serve`
procurou o *bundle* e se a pasta existe — que é o que distingue "não instalado"
de "instalado no sítio errado".

---

## 0. Antes de começar

```bash
python3 --version     # 3.10+ (o install-native.sh exige 3.11+)
docker --version      # só para as vias C e D
free -g               # a via D (:full) quer ~10 GB livres em disco
```

Se vai testar mais do que uma via na mesma máquina, **use um `--db` distinto por
via** (ou `$CASPAR_DB`). Caso contrário partilham a mesma `ccss.db` e o histórico
de uma polui o teste da seguinte.

> **Ordem das opções globais.** `--db` pertence ao grupo, não ao subcomando:
> `caspar --db X scan F` funciona, `caspar scan F --db X` **não**. É silencioso —
> o comando corre, mas contra a base errada.

---

## 1. Modos de instalação

Quatro vias. As A e B dão um `caspar` nativo; as C e D correm em contentor.

| Via | Comando | Traz | Quando usar |
|---|---|---|---|
| **A** — PyPI | `pip install cvm-caspar` | CLI + as 2 consolas | uso normal |
| **A+** — PyPI com servidor | `pip install "cvm-caspar[api]"` | ↑ e mais FastAPI/uvicorn | para a consola web |
| **B** — repositório | `pip install -e .` | ↑ e mais a árvore de fontes | desenvolvimento, reprodução |
| **C** — Docker | `alfilipe/caspar:1.1.1` | tudo excepto o LLM | avaliação isolada |
| **D** — Docker full | `alfilipe/caspar:1.1.1-full` | ↑ e mais Ollama + modelo | `build` sem instalar nada |
| **C−** — Docker slim | `alfilipe/caspar:1.1.1-slim` | só o CLI (sem API/consola) | CI/CD |

### Via A — PyPI (o caminho do utilizador final)

```bash
python3 -m venv /tmp/t-pypi && source /tmp/t-pypi/bin/activate
pip install cvm-caspar
caspar --version                 # → caspar 1.1.1
caspar init                      # obrigatório nesta via, e só nesta
caspar targets                   # → 12 plugins com regras
```

**Porquê o `init` só aqui:** o wheel transporta o *dump* canónico, não a base
construída. As vias B, C e D restauram-no por si.

Teste do extra `[api]` — é o que separa "tenho CLI" de "tenho consola":

```bash
pip install "cvm-caspar[api]"
caspar serve --port 2027          # Ctrl-C para sair
```

> As consolas **já vêm** no `pip install cvm-caspar` (o `dist/` é versionado e vai
> dentro do wheel). O `[api]` acrescenta o *servidor* que as serve, não as
> consolas. Sem `[api]`, o `serve` falha por falta do FastAPI — e é esse o
> comportamento correcto a observar.

### Via B — repositório

```bash
git clone https://github.com/AFilipe-IT/cvm && cd cvm
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api]"
python -m pytest tests/ -q        # → 845 passed (846 recolhidos, 1 saltado)
```

> **O extra `[dev]` não é opcional.** Os módulos de teste da API importam
> `fastapi.testclient` ao nível do módulo; sem ele o `pytest` **falha a recolha em
> silêncio** e reporta um número mais baixo sem erro visível. Um total muito
> abaixo de 845 significa ambiente incompleto, não uma suite mais pequena.

Alternativa com o instalador do repositório:

```bash
./install-native.sh               # venv + pip + restauro do dump, sem Docker
```

> **Ubuntu 22.04:** o `pip install -e .[dev]` pode falhar com `ResolutionTooDeep`.
> Solução: `pip install --upgrade pip` primeiro, e se persistir instalar as
> dependências directamente em vez de pelo extra.

### Via C — Docker

```bash
docker run --rm alfilipe/caspar:1.1.1 --version
docker run --rm -v "$PWD":/workspace alfilipe/caspar:1.1.1 scan /workspace/httpd.conf
```

Ou pelo instalador, que cria um *wrapper* em `~/.local/bin/caspar`:

```bash
curl -fsSL https://raw.githubusercontent.com/AFilipe-IT/CASPAR/master/install.sh | sh
```

> **Montagens.** Só `/workspace` e `/reports` chegam ao *host*. Um `-o` para fora
> desses caminhos escreve dentro do contentor e **perde-se em silêncio** quando
> ele termina.

> **Persistência.** Com `--rm`, os *plugins* obtidos e o histórico sobrevivem
> apenas através do volume `caspar_data` (`CASPAR_DATA_DIR`). Sem ele, cada
> execução começa do zero.

Consola web em contentor:

```bash
docker run --rm -p 2027:2027 alfilipe/caspar:1.1.1 serve --host 0.0.0.0
```

> O `--host 0.0.0.0` é **obrigatório** aqui. Com o `127.0.0.1` por omissão o
> servidor só escuta dentro do contentor e o `-p` não serve de nada.

### Via D — Docker `:full` (com LLM)

```bash
docker run --rm -v caspar_data:/data alfilipe/caspar:1.1.1-full targets
```

~9.4 GB: traz o Ollama e o modelo, e é a única via onde o `build` corre sem
instalar mais nada. É a via a usar na secção 4.

### Critério de aceitação da secção 1

Em qualquer via: `caspar --version` → `1.1.1`, `caspar targets` → 12 alvos,
`caspar doctor` → **0 erros**.

> Um aviso `no caspar_meta table` é aceitável numa base restaurada de *dump*: diz
> que o *reseed* versionado não consegue seguir esta base, não que haja corrupção.

---

## 2. Verificação de base — o caminho feliz

Vale para qualquer via. Estabelece que a instalação mede o que deve.

```bash
caspar demo                                     # escreve caspar-demo/
caspar scan caspar-demo/apache-vulnerable.conf
```

Esperado, e são valores fixos:

| Item | Valor |
|---|---|
| Score | **8.7 · HIGH** |
| Achado mais alto | `User` 8.7 `AV:N/AC:L/Au:N/C:C/I:C/A:N` |
| Cadeias disparadas | **4** (a mais alta 10.0, `privilege-escalation: User → Group`) |
| Manifesto | `caspar 1.1.1 · kb sha256:f595efe56da0 · 35 rules (apache-httpd)` |

> **As cadeias não entram no score.** O global é 8.7 (o pior achado individual),
> não 10.0 (a pior cadeia). A própria saída di-lo: *"chains not scored"*. Não é
> defeito — é decisão de desenho.

> **O score global é o máximo, não a média — e é intencional.**
> `engines/scoring.py::aggregate()` devolve `max(temporal_scores)`. A justificação
> está no código e na dissertação (§4.3): *o risco global de um sistema é
> determinado pela sua pior configuração incorrecta não corrigida*. Uma média
> diluiria um achado crítico numa massa de directivas correctas — bastaria
> acrescentar configuração segura para "baixar" o risco de uma porta aberta.
> Ver §7 para o que isto implica quando se analisam vários serviços.

Contraprova, que é o que dá sentido ao número:

```bash
caspar scan caspar-demo/apache-hardened.conf    # o score desce nas mesmas directivas
```

**Se o digest não for `f595efe56da0`**, pare: a base não é a esperada e nenhuma
comparação de scores adiante é válida.

---

## 3. Comandos CLI

Os 23 comandos, agrupados por aquilo que fazem. Marcados **[LLM]** os que exigem
Ollama (via D, ou instalação local do modelo), e **[REDE]** os que fazem chamadas
externas.

### 3.1 Orientação

```bash
caspar about        # o que é o CVM vs. o CASPAR, e a versão
caspar targets      # plugins com regras
caspar targets --all
caspar demo         # escreve as configurações de exemplo
```

### 3.2 Análise — os 4 modos do `scan`

```bash
caspar scan caspar-demo/apache-vulnerable.conf     # 1: ficheiro
caspar scan /etc/apache2/                          # 2: directório
caspar scan --live apache2                         # 3: serviço instalado
caspar scan docker://httpd:2.4                     # 4: imagem Docker
```

Os modos 3 e 4 precisam, respectivamente, do serviço instalado e do Docker
acessível. Num Ubuntu 22.04 limpo o modo 3 é o mais representativo.

Opções que valem a pena exercitar:

```bash
caspar scan FICHEIRO --report -f html -o reports    # relatório HTML
caspar scan FICHEIRO --report -f json -o reports    # JSON (alimenta diff/badge/report)
caspar scan FICHEIRO --report -f sarif -o reports   # SARIF (GitHub code scanning)
caspar scan FICHEIRO --report -f dashboard --online # dashboard com ECharts via CDN
caspar scan FICHEIRO --show-uncovered               # directivas não cobertas
caspar scan FICHEIRO --service-version 2.4.58       # cruza com CVE/exploits
caspar scan FICHEIRO --threshold 5.0                # sai 1 se o score exceder
caspar scan FICHEIRO --exit-code                    # 2=Critical, 1=acima do limiar, 0=ok
```

Verificação do portão de CI — **é o código de saída que interessa, não o texto**:

```bash
caspar scan caspar-demo/apache-vulnerable.conf --threshold 5.0 ; echo "exit=$?"   # → 1
caspar scan caspar-demo/apache-hardened.conf  --threshold 9.0 ; echo "exit=$?"    # → 0
```

**[LLM]** Avaliação de directivas desconhecidas:

```bash
caspar scan FICHEIRO --assess-unknown
```

> Não determinístico e opt-in. Produz **candidatos de baixa confiança**, não
> achados — não use os resultados para comparar scores entre execuções.

### 3.3 Ciclo de vida de um achado

```bash
caspar explain ServerTokens                      # origem da regra, sem análise
caspar fix caspar-demo/apache-vulnerable.conf --dry-run
caspar suppress ServerTokens                     # aceitar como risco conhecido
caspar scan caspar-demo/apache-vulnerable.conf   # confirmar que sai do score
```

O `--dry-run` no `fix` mostra o que mudaria sem escrever. **Corra-o sempre antes
da versão que escreve.**

O `suppress` cria `.caspar-suppress.json` no directório actual. Para voltar
atrás, apague o ficheiro (ou o registo correspondente).

**[LLM]** `caspar promote DIRECTIVA` — converte um desconhecido avaliado por LLM
em regra permanente. Só faz sentido depois de um `--assess-unknown`.

### 3.4 Histórico e tendência

```bash
caspar history                                   # scores passados
caspar trend                                     # trajectória por entrada
caspar scan A --report -f json -o reports
caspar scan B --report -f json -o reports
caspar diff reports/A.json reports/B.json        # comparar dois scans
caspar report reports/*.json                     # sumário executivo
caspar badge reports/A.json --markdown           # badge shields.io
```

O `diff`, o `report` e o `badge` consomem **JSON**, não HTML: o `-f json` acima
não é opcional.

### 3.5 Monitorização contínua

```bash
caspar watch caspar-demo/apache-vulnerable.conf --interval 30
```

Alerta quando o ficheiro muda. **Bloqueia — sai com Ctrl-C** (não há pausa no
CLI; isso existe só no REST, ver §5).

Em contentor, o `watch` precisa do `/etc` montado para ver a configuração real do
*host*, e convém `--init --name` para o poder parar de forma limpa.

### 3.6 Construção de conhecimento **[LLM] [REDE]**

O grupo mais pesado. **Um `build` real mede-se em horas** (~1h46min medido) — para
testar o caminho, use `--dry-run`.

```bash
caspar plugin fetch --list                       # [REDE] fontes públicas
caspar plugin fetch redis --then-install         # [REDE] obter e instalar
caspar plugin add BENCHMARK.pdf --dry-run        # [LLM] a partir de PDF CIS
caspar plugin manual PLUGIN URL_OU_FICHEIRO      # [LLM] RAG de um manual
caspar build --target nginx --dry-run            # [LLM] popular a base
caspar chain                                     # definir cadeias à mão
```

> **O RAG é de build-time.** Os documentos são ingeridos uma vez no `plugin add
> --manual` e depois lidos do disco em cada análise. Não há *flag* de runtime.

### 3.7 Manutenção **[REDE]**

```bash
caspar doctor                                    # integridade (só leitura)
caspar init --force                              # ⚠️ recria a base
caspar refresh                                   # GEL/GRL do NVD + CISA KEV
caspar fetch-exploits                            # NVD + Exploit-DB
```

> **`init --force` destrói** o histórico de análises e os *plugins* instalados
> pelo utilizador. Só o corra numa base descartável.

O `refresh` e o `fetch-exploits` aceitam chave do NVD; sem ela funcionam, mas com
limite de débito bastante mais apertado.

### 3.8 Publicação

```bash
caspar publish reports/A.json --to URL           # [REDE]
```

**CLI-only por desenho** — não tem equivalente REST, e deliberadamente: o servidor
não deve fazer chamadas autenticadas para terceiros em nome de quem está no
browser.

---

## 4. Consola web

```bash
caspar serve                                     # :2027
```

Três moradas (mais a v1):

| URL | O que é |
|---|---|
| `http://127.0.0.1:2027/app` | **consola v2 — a principal** |
| `http://127.0.0.1:2027/v1/app` | consola v1 (a das figuras da dissertação) |
| `http://127.0.0.1:2027/docs` | Swagger UI |

Verificação rápida por linha de comando:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:2027/api/v1/health   # 200
curl -sL http://127.0.0.1:2027/app/    | head -3    # <!doctype html>
curl -sL http://127.0.0.1:2027/v1/app/ | head -3    # <!doctype html>
```

> `/app` e `/v1/app` respondem **307** — é o redirecto normal para `/app/`. Use
> `curl -L`, ou trate o 307 como sucesso.

Páginas a exercitar na v2: Dashboard, Assessment (*upload* de ficheiro **e**
caminho no servidor), Knowledge Base, Reports, Build, Plugins, Watch, Settings.

**Uma página em branco com 200 no HTML** é quase sempre incompatibilidade entre o
`base` do Vite e o prefixo de montagem: o *bundle* pede os *assets* no prefixo
para que foi construído. Confirme com o *Network* do browser que os
`/app/assets/*.js` dão 200.

### Defeito conhecido (cosmético)

O `index.html` da v1 aponta o favicon para `/app/favicon.svg` em vez de
`/v1/app/favicon.svg`. Consequência: a v1 mostra o ícone da v2. **Todos os
assets funcionais (JS/CSS) da v1 respondem 200** — não afecta o funcionamento.

### API REST

```bash
curl -s http://127.0.0.1:2027/api/v1/health
curl -s http://127.0.0.1:2027/api/v1/targets
curl -s -X POST http://127.0.0.1:2027/api/v1/scans \
     -H 'Content-Type: application/json' \
     -d '{"config_path":"caspar-demo/apache-vulnerable.conf"}'
```

*Upload* a partir do browser (é o que a consola usa):

```bash
curl -s -X POST http://127.0.0.1:2027/api/v1/scans/upload \
     -F 'file=@caspar-demo/apache-vulnerable.conf'
```

Autenticação — **desligada por omissão**, e é isso que se deve confirmar:

```bash
caspar serve                                     # sem chave: aberto
CASPAR_API_KEY=segredo caspar serve              # com chave: POST/DELETE exigem X-API-Key
curl -s -X POST http://127.0.0.1:2027/api/v1/scans -d '{}' ; echo   # → 401 sem a chave
```

> A chave protege **apenas** `POST`/`DELETE` em `/scans` e `/hosts/registry`. Os
> `GET` continuam abertos: **não exponha isto em `0.0.0.0` numa rede não fiável**
> assumindo que a chave chega.

---

## 5. Cobertura CLI ↔ REST

O REST **não** é um espelho do CLI, e as diferenças são propositadas:

| Caso | Onde está | Porquê |
|---|---|---|
| `watch` pausa/retoma/pára | **só REST** | o CLI só pára com Ctrl-C; o controlo de ciclo de vida é capacidade nova |
| `publish` | **só CLI** | o servidor não faz chamadas autenticadas a terceiros por conta do browser |
| `build`, `plugin add/fetch/manual`, `refresh`, `fetch-exploits` | ambos | no REST correm como *jobs* em segundo plano (duram demasiado para um pedido HTTP) |

Verificação dos *jobs* — o `build` responde **202 + `job_id`**, não espera:

```bash
curl -s -X POST http://127.0.0.1:2027/api/v1/builds \
     -H 'Content-Type: application/json' -d '{"target":"nginx","dry_run":true}'
curl -s http://127.0.0.1:2027/api/v1/jobs
curl -s "http://127.0.0.1:2027/api/v1/jobs/JOB_ID/logs?after=0"
```

> **Os *jobs* não sobrevivem a um reinício do servidor.** Um `running` sem *thread*
> viva é marcado `failed` com `interrupted by server restart` no arranque. Com
> `--reload` isso acontece a cada gravação de ficheiro — **não use `--reload` a
> testar *jobs***.

A lista completa está em [`frontend/PARITY.md`](frontend/PARITY.md): cada comando
do `cli/main.py` mapeado a um endpoint ou marcado "CLI-only by design".

---

## 6. Folha de registo

| # | Teste | Esperado | OK? |
|---|---|---|---|
| 1 | Via A: `pip install cvm-caspar` + `init` | `1.1.1`, 12 alvos | |
| 2 | Via A: sem `[api]`, `serve` falha | erro claro de FastAPI em falta | |
| 3 | Via A+: com `[api]`, `serve` arranca | :2027 responde | |
| 4 | Via B: `pytest tests/ -q` | **845 passed** | |
| 5 | Via C: `docker run ... scan` | mesmo score da via A | |
| 6 | Via C: `-o` fora de `/reports` | relatório perde-se (comportamento conhecido) | |
| 7 | Via D: `:full` traz Ollama | `build --dry-run` corre | |
| 8 | `doctor` | 0 erros | |
| 9 | `scan apache-vulnerable.conf` | 8.7 HIGH, 4 cadeias, digest `f595efe56da0` | |
| 10 | `scan apache-hardened.conf` | score mais baixo | |
| 11 | Os 4 modos de `scan` | cada um produz achados | |
| 12 | `--threshold` / `--exit-code` | códigos de saída 1 / 0 | |
| 13 | Formatos html/json/sarif/dashboard | 4 ficheiros em `reports/` | |
| 14 | `explain` / `fix --dry-run` / `suppress` | achado sai do score após `suppress` | |
| 15 | `history` / `trend` / `diff` / `report` / `badge` | consomem os JSON produzidos | |
| 16 | `watch` | alerta ao mudar o ficheiro; Ctrl-C sai | |
| 17 | `plugin fetch --list` | lista fontes públicas | |
| 18 | `build --dry-run` | percorre sem escrever | |
| 19 | Consola v2 `/app` | 8 páginas navegam | |
| 20 | Consola v1 `/v1/app` | carrega (favicon errado é conhecido) | |
| 21 | `/docs` Swagger | endpoints listados | |
| 22 | `POST /scans` e `/scans/upload` | devolvem scan | |
| 23 | `CASPAR_API_KEY` | 401 sem chave em POST | |
| 24 | `POST /builds` | 202 + `job_id`, logs por *polling* | |
| 25 | `init --force` numa base descartável | recria; histórico perdido | |

---

## 7. Problemas conhecidos

| Sintoma | Causa | O que fazer |
|---|---|---|
| `pytest` muito abaixo de 845 | falta o extra `[dev]` | `pip install -e ".[dev]"` |
| `ModuleNotFoundError: tomllib` a recolher `test_packaging.py` | Python 3.10 (o `tomllib` só entrou no 3.11) | corrigido em 2026-08-16: reinstale com `pip install -e ".[dev]"` para obter o `tomli` |
| `serve` falha logo | falta o extra `[api]` | `pip install "cvm-caspar[api]"` |
| Consola em branco, HTML 200 | `base` do Vite ≠ prefixo de montagem | reconstruir com o `CVM_BASE` certo |
| Relatório do Docker desaparece | `-o` fora de `/workspace` ou `/reports` | escrever para um caminho montado |
| Contentor: nada responde no `-p` | falta `--host 0.0.0.0` | acrescentar ao `serve` |
| `--db` ignorado | veio depois do subcomando | `caspar --db X scan F` |
| Digest ≠ `f595efe56da0` | base não é a esperada | não comparar scores; restaurar o *dump* |
| *Job* fica `failed` sozinho | servidor reiniciou (ou `--reload`) | correr `serve` sem `--reload` |
| `ResolutionTooDeep` no Ubuntu 22.04 | resolutor do pip | `pip install --upgrade pip` primeiro |
| Favicon errado em `/v1/app` | defeito conhecido, cosmético | ignorar |
