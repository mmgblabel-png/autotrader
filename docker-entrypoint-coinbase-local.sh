#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown -R autotrader:autotrader /data
    exec gosu autotrader "$@"
fi

exec "$@"
