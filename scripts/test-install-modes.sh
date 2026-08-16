#!/usr/bin/env bash
# test-install-modes.sh — testar as vias de instalação do CVM na mesma máquina,
# isoladas umas das outras, com limpeza entre elas.
#
#   ./scripts/test-install-modes.sh doctor        # diagnóstico do ambiente (comece aqui)
#   ./scripts/test-install-modes.sh pypi          # via A — pip install cvm-caspar
#   ./scripts/test-install-modes.sh repo          # via B — pip install -e .
#   ./scripts/test-install-modes.sh docker        # via C — imagem
#   ./scripts/test-install-modes.sh all           # as três em sequência
#   ./scripts/test-install-modes.sh clean         # apagar TUDO o que este script criou
#   ./scripts/test-install-modes.sh status        # o que existe neste momento
#
# Isolamento: cada via tem o seu venv, a sua base de dados e o seu porto, por
# isso nenhuma vê o histórico da outra. Nada fora de $BASE é tocado.
set -uo pipefail

BASE="${CVM_TEST_BASE:-$HOME/.cvm-test}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PORT_PYPI=2101; PORT_REPO=2102; PORT_DOCKER=2103

c()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
no() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
inf(){ printf '  \033[33m•\033[0m %s\n' "$*"; }

# Um passo = um comando + o que se esperava. Nunca aborta a série: um passo que
# falha é informação, e os seguintes ainda podem revelar mais.
FAILED=0
step() {
  local desc="$1"; shift
  if out=$("$@" 2>&1); then ok "$desc"; else
    no "$desc"; echo "$out" | tail -4 | sed 's/^/      /'; FAILED=$((FAILED+1))
  fi
}

py() {  # o interpretador a usar: 3.10+ e não o do venv activo
  command -v python3 >/dev/null || { echo "python3 não encontrado" >&2; exit 1; }
  echo python3
}

# ------------------------------------------------------------------ doctor
cmd_doctor() {
  c "== Diagnóstico do ambiente =="
  local pv; pv=$($(py) --version 2>&1)
  inf "$pv"
  if $(py) -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)'; then
    ok "tomllib disponível (3.11+)"
  else
    inf "Python 3.10 — o extra [dev] instala 'tomli' para test_packaging.py"
  fi
  command -v docker >/dev/null && ok "docker presente" || inf "sem docker (vias C/D indisponíveis)"
  local free; free=$(df -BG --output=avail "$HOME" 2>/dev/null | tail -1 | tr -dc '0-9')
  [ "${free:-0}" -ge 12 ] && ok "espaço livre ${free}G" || inf "espaço livre ${free:-?}G (a imagem :full quer ~10G)"

  c "== Consolas nesta árvore =="
  for d in frontend-v2/dist frontend/dist; do
    if [ -f "$REPO/$d/index.html" ]; then ok "$d presente"; else
      no "$d EM FALTA — 'pip install -e .' falha (force-include do hatchling)"; FAILED=$((FAILED+1)); fi
  done
  echo; [ "$FAILED" -eq 0 ] && c "Ambiente pronto." || c "$FAILED problema(s)."
}

# -------------------------------------------------- diagnóstico das consolas
# Responde à pergunta "porque é que /app dá 404?" olhando para onde o código
# procura o bundle — em vez de adivinhar a partir do sintoma.
probe_consoles() {
  local venv="$1"
  "$venv/bin/python" - <<'PY'
from pathlib import Path
try:
    import cli.commands.serve_cmds as s
except Exception as e:
    print(f"      não consegui importar serve_cmds: {e}"); raise SystemExit(0)
for nome, fn in (("v2 (/app)", "_console_v2_dist"), ("v1 (/v1/app)", "_console_dist")):
    f = getattr(s, fn, None)
    if f is None:
        print(f"      {nome}: {fn}() não existe nesta versão"); continue
    p = f()
    idx = (p / "index.html").is_file()
    print(f"      {nome}: {p}")
    print(f"           dir={p.is_dir()}  index.html={idx}")
    if p.is_dir() and not idx:
        print("           → pasta existe mas sem index.html: bundle por construir")
    elif not p.is_dir():
        print("           → NÃO EXISTE: é esta a causa do 404")
PY
}

http() { curl -s -o /dev/null -w "%{http_code}" -L --max-time 5 "$1" 2>/dev/null || echo 000; }

serve_check() {
  local venv="$1" port="$2" db="$3" label="$4"
  c "-- consolas e API ($label) --"
  CASPAR_DB="$db" "$venv/bin/caspar" serve --port "$port" > "$BASE/serve-$label.log" 2>&1 &
  local pid=$!
  for _ in $(seq 1 25); do [ "$(http "http://127.0.0.1:$port/api/v1/health")" = 200 ] && break; sleep 1; done

  local h a v d; h=$(http "http://127.0.0.1:$port/api/v1/health")
  a=$(http "http://127.0.0.1:$port/app/"); v=$(http "http://127.0.0.1:$port/v1/app/")
  d=$(http "http://127.0.0.1:$port/docs")
  [ "$h" = 200 ] && ok "API /health 200" || { no "API /health $h"; FAILED=$((FAILED+1)); }
  [ "$a" = 200 ] && ok "consola v2 /app 200" || { no "consola v2 /app → $a"; FAILED=$((FAILED+1)); }
  [ "$v" = 200 ] && ok "consola v1 /v1/app 200" || { no "consola v1 /v1/app → $v"; FAILED=$((FAILED+1)); }
  [ "$d" = 200 ] && ok "Swagger /docs 200" || no "Swagger /docs → $d"

  if [ "$a" != 200 ] || [ "$v" != 200 ]; then
    inf "diagnóstico — onde o serve procura os bundles:"
    probe_consoles "$venv"
    inf "arranque:"; grep -i "console\|not found\|error" "$BASE/serve-$label.log" | head -5 | sed 's/^/      /'
  fi
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
}

# Os valores fixos que qualquer via tem de reproduzir. Um score diferente aqui
# vale mais do que qualquer teste unitário: significa que a base não é a mesma.
scan_check() {
  local venv="$1" db="$2" label="$3"
  c "-- verificação funcional ($label) --"
  local wd="$BASE/work-$label"; mkdir -p "$wd"
  ( cd "$wd" && CASPAR_DB="$db" "$venv/bin/caspar" demo >/dev/null 2>&1 )
  local out; out=$(cd "$wd" && CASPAR_DB="$db" "$venv/bin/caspar" scan caspar-demo/apache-vulnerable.conf 2>&1)

  grep -q "8.7" <<<"$out" && ok "score 8.7 (esperado)" || { no "score != 8.7"; FAILED=$((FAILED+1)); }
  grep -qi "HIGH" <<<"$out" && ok "severidade HIGH" || no "severidade inesperada"
  if grep -q "f595efe56da0" <<<"$out"; then ok "kb sha256:f595efe56da0"
  else
    no "digest diferente do esperado — scores não comparáveis"
    grep -o "kb sha256:[a-f0-9]*" <<<"$out" | head -1 | sed 's/^/      obtido: /'
    FAILED=$((FAILED+1))
  fi
  local n; n=$(CASPAR_DB="$db" "$venv/bin/caspar" targets 2>/dev/null | grep -cE "^  [a-z]")
  [ "${n:-0}" -ge 12 ] && ok "$n alvos com regras" || inf "${n:-0} alvos (esperados 12)"

  # o portão de CI é o código de saída, não o texto
  ( cd "$wd" && CASPAR_DB="$db" "$venv/bin/caspar" scan caspar-demo/apache-vulnerable.conf -t 5.0 >/dev/null 2>&1 )
  [ $? -eq 1 ] && ok "--threshold devolve 1 acima do limiar" || no "--threshold: código de saída inesperado"
}

# ------------------------------------------------------------------ via A
cmd_pypi() {
  c "== Via A — PyPI =="
  local v="$BASE/venv-pypi" db="$BASE/pypi.db"
  rm -rf "$v"; $(py) -m venv "$v"
  step "pip install cvm-caspar[api]" "$v/bin/pip" install --quiet "cvm-caspar[api]"
  inf "versão: $("$v/bin/caspar" --version 2>&1)"
  step "caspar init"  env CASPAR_DB="$db" "$v/bin/caspar" init --force
  step "caspar doctor" env CASPAR_DB="$db" "$v/bin/caspar" doctor
  scan_check "$v" "$db" "pypi"
  serve_check "$v" "$PORT_PYPI" "$db" "pypi"
}

# ------------------------------------------------------------------ via B
cmd_repo() {
  c "== Via B — repositório =="
  local v="$BASE/venv-repo" db="$BASE/repo.db"
  rm -rf "$v"; $(py) -m venv "$v"
  "$v/bin/pip" install --quiet --upgrade pip
  step "pip install -e .[dev,api]" "$v/bin/pip" install --quiet -e "$REPO[dev,api]"
  inf "versão: $("$v/bin/caspar" --version 2>&1)"

  c "-- suite de testes --"
  local t; t=$(cd "$REPO" && "$v/bin/python" -m pytest tests/ -q 2>&1 | tail -3)
  echo "$t" | sed 's/^/      /'
  if grep -qE "^[0-9]+ passed|[0-9]+ passed," <<<"$t"; then
    local n; n=$(grep -oE "[0-9]+ passed" <<<"$t" | head -1 | grep -oE "[0-9]+")
    [ "${n:-0}" -ge 845 ] && ok "$n testes passados" \
      || { no "$n testes (esperados ≥845) — extra [dev] em falta?"; FAILED=$((FAILED+1)); }
  else
    no "a suite não chegou a correr"; FAILED=$((FAILED+1))
  fi

  step "caspar init" env CASPAR_DB="$db" "$v/bin/caspar" init --force
  scan_check "$v" "$db" "repo"
  serve_check "$v" "$PORT_REPO" "$db" "repo"
}

# ------------------------------------------------------------------ via C
cmd_docker() {
  c "== Via C — Docker =="
  command -v docker >/dev/null || { inf "docker ausente — via saltada"; return; }
  local img="${CVM_IMAGE:-alfilipe/caspar:1.1.1}" wd="$BASE/work-docker"
  mkdir -p "$wd"
  step "docker pull $img" docker pull -q "$img"
  inf "versão: $(docker run --rm "$img" --version 2>&1)"

  ( cd "$wd" && docker run --rm -v "$wd:/workspace" "$img" demo >/dev/null 2>&1 )
  local out; out=$(docker run --rm -v "$wd:/workspace" "$img" scan /workspace/caspar-demo/apache-vulnerable.conf 2>&1)
  grep -q "8.7" <<<"$out" && ok "score 8.7 (igual às vias nativas)" \
    || { no "score != 8.7 em contentor"; echo "$out" | tail -3 | sed 's/^/      /'; FAILED=$((FAILED+1)); }

  c "-- consola em contentor --"
  # --host 0.0.0.0 é obrigatório: com o 127.0.0.1 por omissão o -p não serve de nada
  local cid; cid=$(docker run -d --rm -p "$PORT_DOCKER:2027" "$img" serve --host 0.0.0.0 2>/dev/null)
  if [ -n "$cid" ]; then
    for _ in $(seq 1 25); do [ "$(http "http://127.0.0.1:$PORT_DOCKER/api/v1/health")" = 200 ] && break; sleep 1; done
    [ "$(http "http://127.0.0.1:$PORT_DOCKER/api/v1/health")" = 200 ] && ok "API 200" || { no "API não responde"; FAILED=$((FAILED+1)); }
    [ "$(http "http://127.0.0.1:$PORT_DOCKER/app/")" = 200 ] && ok "consola v2 200" || { no "consola v2 não responde"; FAILED=$((FAILED+1)); }
    docker stop "$cid" >/dev/null 2>&1
  else no "o contentor não arrancou"; FAILED=$((FAILED+1)); fi
}

# ------------------------------------------------------------------ limpeza
cmd_clean() {
  c "== Limpeza =="
  # Só o que este script criou. O repositório e a ccss.db de trabalho não são tocados.
  for p in $PORT_PYPI $PORT_REPO $PORT_DOCKER; do
    pkill -f "caspar serve --port $p" 2>/dev/null && inf "servidor :$p terminado"
  done
  if command -v docker >/dev/null; then
    local ids; ids=$(docker ps -q --filter "ancestor=${CVM_IMAGE:-alfilipe/caspar:1.1.1}" 2>/dev/null)
    [ -n "$ids" ] && { docker stop $ids >/dev/null 2>&1; inf "contentores parados"; }
  fi
  if [ -d "$BASE" ]; then
    local sz; sz=$(du -sh "$BASE" 2>/dev/null | cut -f1)
    rm -rf "$BASE"; ok "$BASE removido ($sz)"
  else ok "nada a limpar"; fi
  inf "as imagens Docker ficam (docker rmi ${CVM_IMAGE:-alfilipe/caspar:1.1.1} para as apagar)"
}

cmd_status() {
  c "== Estado =="
  [ -d "$BASE" ] || { inf "$BASE não existe — nada instalado por este script"; return; }
  inf "base: $BASE ($(du -sh "$BASE" 2>/dev/null | cut -f1))"
  for v in venv-pypi venv-repo; do
    [ -x "$BASE/$v/bin/caspar" ] && ok "$v → $("$BASE/$v/bin/caspar" --version 2>&1)"
  done
  for p in $PORT_PYPI $PORT_REPO $PORT_DOCKER; do
    pgrep -f "caspar serve --port $p" >/dev/null && inf "servidor activo em :$p"
  done
}

mkdir -p "$BASE"
case "${1:-doctor}" in
  doctor) cmd_doctor ;;
  pypi)   cmd_pypi ;;
  repo)   cmd_repo ;;
  docker) cmd_docker ;;
  all)    cmd_doctor; cmd_pypi; cmd_repo; cmd_docker ;;
  clean)  cmd_clean; exit 0 ;;
  status) cmd_status; exit 0 ;;
  *) sed -n '2,18p' "$0"; exit 1 ;;
esac

echo
if [ "$FAILED" -eq 0 ]; then c "Tudo passou."; else c "$FAILED verificação(ões) falharam."; fi
exit $((FAILED > 0))
