#!/usr/bin/env sh
set -eu

: "${PORT:=8000}"
: "${DATA_DIR:=/data}"

# Railway mounts persistent volumes after image build. A new mount can be root-owned,
# so repair only this directory before dropping back to the non-root app account.
if [ "$(id -u)" -eq 0 ]; then
    mkdir -p "$DATA_DIR"
    chown -R app:app "$DATA_DIR"
    exec su -p -s /bin/sh app -c /app/scripts/start.sh
fi

mkdir -p "$DATA_DIR"
python -m campaign_automaton init >/tmp/campaign-automaton-init.json
exec uvicorn app:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips="*"
