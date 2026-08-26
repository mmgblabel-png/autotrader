#!/usr/bin/env sh
set -eu

: "${PORT:=8000}"
: "${DATA_DIR:=/data}"

mkdir -p "$DATA_DIR"
python -m campaign_automaton init >/tmp/campaign-automaton-init.json
exec uvicorn app:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips="*"
