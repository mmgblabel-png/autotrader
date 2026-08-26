# Railway Infrastructure as Code

Railway’s current project-level configuration is defined in `railway.ts`. The older root-level `railway.json` format is deprecated and is not the source of truth for new deployments.

## Required variables

Create the following values in the Railway service before applying or deploying:

| Variable | Purpose |
|---|---|
| `PUBLIC_BASE_URL` | Final HTTPS service domain, without a trailing slash |
| `CONTROL_TOKEN` | Long random secret protecting campaign and approval endpoints |
| `WEBHOOK_TOKEN` | Separate long random secret protecting conversion/event callbacks |
| `PAYPRO_AFFILIATE_ID` | Your own PayPro affiliate identifier |
| `PAYPRO_AFFILIATE_URL_TEMPLATE` | Exact PayPro affiliate URL format; use `{product_url}` and/or `{affiliate_id}` |
| `OPENAI_API_KEY` | Optional; omit it to run the deterministic no-cost content fallback |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible endpoint; omit for the standard provider default |

Generate tokens locally with `openssl rand -hex 32`. Do not commit their values.

## Apply

```bash
railway login
railway link
railway config plan
railway config apply
```

Review the plan before applying. The definition creates one service and one 512 MB volume mounted at `/data`. One replica is intentional because Railway volumes cannot be shared by service replicas. The health check is `/api/health`.

After Railway assigns a domain, set `PUBLIC_BASE_URL=https://<your-domain>` and redeploy. Verify:

```bash
curl https://<your-domain>/api/health
curl -H "X-Control-Token: $CONTROL_TOKEN" \
  https://<your-domain>/api/config/status
```

Keep `DRAFT_ONLY=true` until a separate, platform-compliant publishing connector and a human approval procedure have been reviewed.
