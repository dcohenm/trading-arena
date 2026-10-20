#!/bin/bash
# Corre la evaluación de Kronos en tu Mac (usa la GPU del chip M). Todo queda en ~/trading-arena-local.
# Uso:  curl -fsSL https://raw.githubusercontent.com/dcohenm/trading-arena/main/mac/run_kronos_mac.sh | bash
set -euo pipefail
DIR="$HOME/trading-arena-local"
KRONOS_COMMIT="67b630e67f6a18c9e9be918d9b4337c960db1e9a"
say() { printf "\n\033[1m== %s\033[0m\n" "$1"; }

say "1/4 Bajando el proyecto en $DIR"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q --ff-only; else git clone -q https://github.com/dcohenm/trading-arena.git "$DIR"; fi
cd "$DIR"

say "2/4 Preparando Python (en una carpeta aparte, no toca tus entornos de conda)"
PY=""
for c in "$HOME/miniconda3/bin/python3" "$(command -v python3 || true)"; do
  if [ -n "$c" ] && [ -x "$c" ] && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then echo "No encontré Python 3.10 o más nuevo."; exit 1; fi
[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt torch einops==0.8.1 "huggingface_hub>=0.33" safetensors tqdm
[ -d vendor/Kronos/.git ] || git clone -q https://github.com/shiyu-coder/Kronos.git vendor/Kronos
git -C vendor/Kronos fetch -q origin "$KRONOS_COMMIT" 2>/dev/null || true
git -C vendor/Kronos checkout -q "$KRONOS_COMMIT"
python -c "import torch; print('GPU del chip M disponible:', torch.backends.mps.is_available())"

export PYTORCH_ENABLE_MPS_FALLBACK=1
say "3/4 Kronos-small: todas las predicciones (la Mac no se va a dormir mientras corre)"
caffeinate -i python kronos_eval.py --full --device auto --model small --tag mac_small --exchanges binance,coinbase,okx

say "4/4 Kronos-base (4 veces más grande, tarda más; si falla no pasa nada)"
caffeinate -i python kronos_eval.py --full --device auto --model base --tag mac_base --exchanges binance,coinbase,okx || echo "Kronos-base no terminó; los resultados de Kronos-small igual sirven."

open docs/kronos_mac_small/index.html 2>/dev/null || true
say "Listo. Avisale a Claude que terminó."
