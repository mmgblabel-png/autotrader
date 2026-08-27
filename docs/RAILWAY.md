# Railway Deployment Runbook

**Author:** Manus AI  
**Application:** WegMetDieKilos Campaign Automaton

## 1. Deployment model

Deploy one `campaign-automaton` service from the repository root and mount one persistent volume at `/data`. The API and heartbeat run in the same process. Railway detects a root `Dockerfile`, injects `PORT`, and uses the configured health endpoint during activation.[1] [2]

Railway deployment filesystems are ephemeral unless a volume is attached.[3] The included `.railway/railway.ts` creates a 512 MB volume, one service replica, and `/api/health` as the health check. One replica is required because Railway volumes cannot be used with replicas.[4]

## 2. Required service variables

Set these through the Railway dashboard or CLI before the first production deployment.

| Variable | Required | Example or rule |
|---|---:|---|
| `APP_ENV` | Yes | `production` |
| `DATA_DIR` | Yes | `/data` |
| `DATABASE_PATH` | Yes | `/data/campaign_automaton.db` |
| `CAMPAIGN_CONFIG_PATH` | Yes | `/app/config/campaign.yaml` |
| `PUBLIC_BASE_URL` | Yes | Final Railway HTTPS domain, no trailing slash |
| `PAYPRO_PRODUCT_URL` | Yes | Exact supplied PayPro destination |
| `PAYPRO_AFFILIATE_ID` | Account-dependent | Operator’s own identifier |
| `PAYPRO_AFFILIATE_URL_TEMPLATE` | Account-dependent | Exact format containing `{product_url}` and/or `{affiliate_id}` |
| `CONTROL_TOKEN` | Yes | `openssl rand -hex 32` |
| `WEBHOOK_TOKEN` | Yes | Different `openssl rand -hex 32` value |
| `DRAFT_ONLY` | Yes | `true` |
| `AUTO_RUN_DUE_CAMPAIGNS` | Yes | `false` for setup |
| `DAILY_TIKTOK_REVIEW_ENABLED` | Optional | `true` only for one internal, policy-checked review candidate per day; it never uploads or posts to TikTok |
| `DAILY_TIKTOK_REVIEW_CAMPAIGNS` | Optional | Comma-separated active campaign slugs eligible for internal review, for example `freds-bouwtekeningen,communicatie-canvas` |
| `OPENAI_API_KEY` | Optional | Omit for deterministic mode |
| `OPENAI_BASE_URL` | Optional | OpenAI-compatible endpoint |

Never put secret values in `.railway/railway.ts`, `.env.example`, Docker build arguments, source files, or Git history.

## 3. Apply infrastructure

Railway’s current project-level format is `.railway/railway.ts`. The older `railway.json`/`railway.toml` format is deprecated and stops being read after 2026-12-01.[5]

```bash
railway login
railway link
railway config plan
railway config apply
```

Review the plan before applying. Destructive changes should never be accepted automatically. The plan should create or retain exactly one application service and one campaign-data volume.

## 4. First deployment

The Docker container executes `scripts/start.sh`, which creates the data directory, initializes the schema and default campaign idempotently, and starts Uvicorn on Railway’s `PORT`.

After Railway assigns a public domain, set:

```text
PUBLIC_BASE_URL=https://<assigned-domain>
```

Redeploy and verify:

```bash
export BASE=https://<assigned-domain>

curl "$BASE/api/health"
curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/config/status"
```

The health result should report `status=ok`, `database_ok=true`, and a running heartbeat when enabled. Configuration status should report `draft_only=true` and an affiliate configuration that is ready for the chosen URL template.

## 5. End-to-end staging check

Run one deterministic or model-assisted content workflow:

```bash
curl -X POST "$BASE/api/campaigns/wegmetdiekilos-bronze/runs" \
  -H "Content-Type: application/json" \
  -H "X-Control-Token: $CONTROL_TOKEN" \
  -H "Idempotency-Key: railway-staging-1" \
  -d '{"workflow":"content","channels":["blog","email","social"],"force":false}'
```

Inspect drafts:

```bash
curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/campaigns/wegmetdiekilos-bronze/artifacts"
```

Test the tracking redirect without following it:

```bash
curl -I "$BASE/r/wegmetdiekilos-bronze?src=railway-test&content=smoke-1"
```

Confirm that the `Location` header points to the exact expected PayPro destination and includes the expected UTM fields. Then verify that analytics show one click.

## 6. Callback integration

Do not assume PayPro offers a usable affiliate conversion webhook for this account. Confirm the callback format in the operator’s current PayPro documentation or dashboard before connecting it. When a verified provider or analytics service can send events, map its payload into:

```json
{
  "provider": "verified-provider-name",
  "event": {
    "campaign_slug": "wegmetdiekilos-bronze",
    "event_type": "conversion",
    "source": "blog",
    "medium": "affiliate",
    "content_id": "artifact-id",
    "event_id": "stable-provider-event-id",
    "value": 0,
    "metadata": {}
  }
}
```

Send it to `/api/webhooks/events` with `X-Webhook-Token`. Use a stable `event_id` so retries remain idempotent. Exclude direct identifiers and health information.

## 7. Enabling scheduled runs

Complete all staging checks before changing `AUTO_RUN_DUE_CAMPAIGNS` to `true`. Confirm model request budgets, review capacity, affiliate links, campaign schedule, disclosure, and policy behavior first. Activate the campaign through the CLI locally or the protected PATCH endpoint.

Keep publication outside the runtime. Scheduled work creates drafts and proposals; it does not post, email, message, or purchase anything.

### Daily TikTok review queue

When `DAILY_TIKTOK_REVIEW_ENABLED=true`, the heartbeat creates at most **one** internal TikTok review candidate per local calendar day across `DAILY_TIKTOK_REVIEW_CAMPAIGNS`. The queue records an ordinary draft artifact, its deterministic content-policy result, the proposed first-party UTM route, and an append-only audit event. It cannot call TikTok, upload media, publish a post, approve an artifact, send a message, or change a campaign. Before any potential post, the owner must separately review the final media and editable caption, confirm the channel is allowed by the merchant, choose commercial disclosure and visibility, and give explicit approval for that exact post.

## 8. Persistence verification

After creating a test artifact and event, trigger one ordinary redeploy. Re-run the artifact and analytics queries. Records must remain present. If they disappear, verify the volume is mounted at `/data` and `DATABASE_PATH` points to `/data/campaign_automaton.db`.

Railway documents that services with attached volumes experience a small amount of redeployment downtime because overlapping mounts are blocked to protect data integrity.[4]

## 9. Operations

| Operation | Procedure |
|---|---|
| Health | Monitor `/api/health` externally; Railway health checks are deployment-time, not continuous monitoring.[2] |
| Logs | Use Railway deployment logs; do not log tokens or raw webhook secrets |
| Backups | Use Railway volume backups and periodic SQLite backup exports |
| Budget | Check model request caps and `llm_mode` before enabling automatic runs |
| Pause | PATCH the campaign to `paused` or set `AUTO_RUN_DUE_CAMPAIGNS=false` |
| Emergency stop | Set `HEARTBEAT_ENABLED=false`, redeploy, and keep the API available for review/export |
| Secret rotation | Set a new token in Railway, redeploy, update integrations, then remove the old value |

## 10. Rollback

Application rollback can redeploy an earlier Git commit. Database schema changes are forward-managed by the runtime, so back up the volume before future migrations. Do not delete or detach the volume to perform an application rollback. Railway treats volume deletion, detachment, or placement changes as destructive.[6]

## 11. References

[1]: https://docs.railway.com/builds/dockerfiles "Railway Docs — Dockerfiles"
[2]: https://docs.railway.com/deployments/healthchecks "Railway Docs — Healthchecks"
[3]: https://docs.railway.com/deployments/reference "Railway Docs — Deployments reference"
[4]: https://docs.railway.com/volumes/reference "Railway Docs — Volumes"
[5]: https://docs.railway.com/infrastructure-as-code "Railway Docs — Infrastructure as Code"
[6]: https://docs.railway.com/infrastructure-as-code/reference "Railway Docs — Infrastructure as Code Reference"
