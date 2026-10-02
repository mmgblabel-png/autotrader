#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data /data/logs /app/exports /app/logs
    chown -R autotrader:autotrader /data /app/exports /app/logs
    exec gosu autotrader "$@"
fi

exec "$@"
