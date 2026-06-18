#!/usr/bin/env bash
# Scripted command-line demo for asciinema. [spec §8]
# Brings up the stack and runs the worked-use-case smoke test end-to-end.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "▶ VCL reference implementation — one-shot demo"
echo "▶ Companion paper: Zenodo DOI 10.5281/zenodo.20599942"
echo

echo "\$ docker compose up -d --build"
docker compose up -d --build

echo
echo "\$ python scripts/smoke.py   # worked use case end-to-end"
python scripts/smoke.py

echo
echo "▶ Open http://localhost:8501 for the UI walkthrough (see docs/demo-script.md)."
echo "▶ Tear down with:  docker compose down -v"
