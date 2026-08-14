#!/bin/bash
# install-native.sh — instalação local do CASPAR numa máquina nova (sem Docker).
# Para instalação automática com Docker (traz Ollama incluído), usa install.sh.
set -e
echo "=== CASPAR Install ==="

# Verificar Python 3.11+
python3 --version || { echo "Python 3.11+ required"; exit 1; }

# Virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Instalar
pip install --upgrade pip --quiet
# Com o extra [api]: sem ele o 'caspar serve' — e portanto toda a consola web —
# rebentava com ModuleNotFoundError numa instalação nativa, obrigando a um
# 'pip install -e ".[api]"' manual que ninguém adivinha. A consola vem
# construída no repositório, logo esta é a única peça que falta para o serve
# funcionar de origem.
pip install -e ".[api]" --quiet

# Restaurar base de dados canónica a partir do SQL
sqlite3 ccss.db < data/ccss_canonical.sql

# As duas consolas vêm construídas no repositório (frontend/dist e
# frontend-v2/dist são versionados), precisamente para não obrigar ninguém a
# instalar Node. O 'pip install -e' acima é editable, por isso o 'caspar serve'
# serve estas pastas directamente.
# Só avisamos se faltarem: quem apagou um dist ou clonou parcialmente fica a
# saber porque é que a consola não aparece, em vez de descobrir com um 404.
# Cada uma é verificada em separado — o 'serve' monta-as em prefixos distintos e
# uma pode faltar sem a outra.
for console in "frontend-v2:/app" "frontend:/v1/app"; do
    dir="${console%%:*}"
    prefix="${console##*:}"
    if [ ! -f "$dir/dist/index.html" ]; then
        echo "⚠️  $dir/dist ausente — a consola $prefix não vai estar disponível." >&2
        echo "    A API REST funciona na mesma. Para a repor: git checkout $dir/dist" >&2
    fi
done

echo ""
echo "✅ CASPAR instalado com sucesso"
echo "   Activar: source .venv/bin/activate"
echo "   Testar:  caspar targets"
echo "   Consola: caspar serve   →  http://127.0.0.1:2027/app      (v2)"
echo "            consola v1     →  http://127.0.0.1:2027/v1/app"
echo ""
echo "Para build-time (plugin add, build):"
echo "   Instalar Ollama: https://ollama.ai"
echo "   Descarregar modelo: ollama pull qwen2.5:14b"
