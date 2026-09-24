#!/usr/bin/env bash
set -euo pipefail

: "${RAILWAY_PROJECT_ID:=7ae8abad-fda5-413f-8fd6-b33634bf311f}"
: "${RAILWAY_ENVIRONMENT:=production}"
: "${RAILWAY_SERVICE_ID:=64c12689-f47d-4b3f-b594-d839bb5440eb}"
: "${RAILWAY_VOLUME_NAME:=autotrader-orders}"
: "${RAILWAY_VOLUME_MOUNT_PATH:=/app/data}"

command -v railway >/dev/null || { echo 'Install/authenticate Railway CLI first: https://docs.railway.com/cli'; exit 2; }

echo '1) Add persistent volume (run once; review Railway plan/cost first)'
railway volume add \
  --project "$RAILWAY_PROJECT_ID" \
  --environment "$RAILWAY_ENVIRONMENT" \
  --service "$RAILWAY_SERVICE_ID" \
  --mount-path "$RAILWAY_VOLUME_MOUNT_PATH" \
  --name "$RAILWAY_VOLUME_NAME"

echo '2) Set the journal path in the service environment'
echo "ORDER_JOURNAL_PATH=$RAILWAY_VOLUME_MOUNT_PATH/orders.sqlite3"

echo 'Add this variable in Railway Variables, then redeploy.'

echo '3) Enable static outbound IPs (Railway Pro required)'
railway outbound-network static-ip enable --service "$RAILWAY_SERVICE_ID"
railway outbound-network static-ip status --service "$RAILWAY_SERVICE_ID" --json

echo '4) Add every displayed static IPv4 address to the Bitvavo API-key IP whitelist.'
echo '5) Redeploy, then verify the service egress IP and run the security script.'
