#!/usr/bin/env bash
set -euo pipefail

# Read-only production connectivity test.
# This script never places, cancels, or modifies an exchange order.

SERVICE="${RAILWAY_SERVICE:-autotrader}"
ENVIRONMENT="${RAILWAY_ENVIRONMENT:-production}"
KEY_FILE="${RAILWAY_SSH_KEY:-$HOME/.ssh/railway_autotrader}"

if ! command -v railway >/dev/null 2>&1; then
  echo "ERROR: Railway CLI is not installed or not on PATH." >&2
  exit 2
fi

if [[ ! -f "$KEY_FILE" ]]; then
  echo "ERROR: SSH private key not found: $KEY_FILE" >&2
  echo "Create it with: ssh-keygen -t ed25519 -f '$KEY_FILE' -C 'autotrader-railway'" >&2
  echo "Then register it with: railway ssh keys add --key '$KEY_FILE' --name autotrader-production" >&2
  exit 3
fi

if [[ ! -f "${KEY_FILE}.pub" ]]; then
  echo "ERROR: Public key not found: ${KEY_FILE}.pub" >&2
  exit 4
fi

echo "== Railway project context =="
railway status | sed -n '1,24p'

echo "== Registered SSH keys (metadata only) =="
railway ssh keys list

echo "== Remote identity test =="
railway ssh \
  --service "$SERVICE" \
  --environment "$ENVIRONMENT" \
  --identity-file "$KEY_FILE" \
  -- python -c 'import os,socket; print({"remote_execution":"OK","hostname":socket.gethostname(),"venue":os.getenv("EXCHANGE_VENUE","unset"),"mode":os.getenv("EXECUTION_MODE","unset")})'

echo "== Remote Bitpanda read-only authentication test =="
railway ssh \
  --service "$SERVICE" \
  --environment "$ENVIRONMENT" \
  --identity-file "$KEY_FILE" \
  -- python -c 'import json; from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter; a=BitpandaFusionAdapter(); r=a.authenticate(); print(json.dumps({"venue":r.get("venue"),"credentials_present":r.get("credentials_present"),"authenticated":r.get("authenticated"),"endpoint":r.get("endpoint"),"response_type":r.get("response_type"),"balance_entries":r.get("balance_entries")}, default=str))'

echo "== Remote read-only BTC-EUR open-orders test =="
railway ssh \
  --service "$SERVICE" \
  --environment "$ENVIRONMENT" \
  --identity-file "$KEY_FILE" \
  -- python -c 'import json; from autotrader.connectors.bitpanda_fusion import BitpandaFusionAdapter; r=BitpandaFusionAdapter().open_orders(pair="BTC-EUR"); print(json.dumps({"pair":"BTC-EUR","open_order_count":len(r) if isinstance(r,list) else None,"response_type":type(r).__name__}, default=str))'

echo "PASS: SSH and read-only Bitpanda authentication checks completed."
echo "No order, cancellation, or live execution was attempted."
