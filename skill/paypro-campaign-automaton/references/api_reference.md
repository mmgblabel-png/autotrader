# Campaign Automaton API Reference

## Authentication

Use `X-Control-Token` for campaign, run, artifact, approval, analytics, audit, and manual-event endpoints. Use a separate `X-Webhook-Token` for `/api/webhooks/events`. Public endpoints are limited to `/`, `/api/health`, API documentation, and tracked redirects under `/r/{campaign_slug}`.

## Endpoints

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| GET | `/api/health` | Public | Database, scheduler, model-mode, and readiness status |
| GET | `/api/config/status` | Control | Safe configuration summary without secret values |
| GET/POST | `/api/campaigns` | Control | List or create campaigns |
| GET/PATCH | `/api/campaigns/{slug}` | Control | Read or update a campaign |
| POST | `/api/campaigns/{slug}/clone` | Control | Clone safe configuration without events, approvals, or secrets |
| POST | `/api/campaigns/{slug}/runs` | Control | Run `full_campaign`, `research`, `seo`, `content`, or `analytics` |
| GET | `/api/campaigns/{slug}/runs` | Control | Run history |
| GET | `/api/runs/{id}` | Control | One run and summary |
| GET | `/api/campaigns/{slug}/artifacts` | Control | Versioned artifacts, optional `status` filter |
| GET | `/api/artifacts/{id}` | Control | One artifact with metadata and policy decision |
| POST | `/api/artifacts/{id}/review` | Control | Approve or reject; blocked artifacts cannot be approved |
| GET | `/api/campaigns/{slug}/analytics` | Control | Views, clicks, signups, conversions, value, and rates |
| GET | `/api/campaigns/{slug}/optimizations` | Control | Analytics proposals awaiting a human decision |
| POST | `/api/optimizations/{id}/decision` | Control | Accept or reject a reversible experiment proposal |
| GET | `/api/audit` | Control | Append-only operator and system audit events |
| POST | `/api/events` | Control | Manual pseudonymous test or imported event |
| POST | `/api/webhooks/events` | Webhook | Idempotent provider callback ingestion |
| GET | `/r/{campaign_slug}` | Public | Record a click and redirect to the resolved PayPro URL |

## Run request

```json
{
  "workflow": "full_campaign",
  "channels": ["blog", "email", "social"],
  "force": false
}
```

Supply `Idempotency-Key` to control retries explicitly. Without it, non-forced runs deduplicate by campaign, workflow, channel set, and UTC date. `force=true` creates a new run.

## Artifact review

```json
{
  "decision": "approved",
  "reviewer": "owner",
  "notes": "Claims, source gaps, disclosure, destination, and channel policy checked."
}
```

Only `approved` and `rejected` are valid review decisions. A policy result containing `allowed=false` prevents approval.

## Webhook event

```json
{
  "provider": "custom",
  "occurred_at": "2026-08-26T12:00:00Z",
  "event": {
    "campaign_slug": "wegmetdiekilos-bronze",
    "event_type": "conversion",
    "source": "blog",
    "medium": "affiliate",
    "content_id": "artifact-id",
    "event_id": "provider-unique-id",
    "value": 0,
    "metadata": {}
  }
}
```

Accepted event types are `view`, `click`, `signup`, and `conversion`. `event_id` is the deduplication key. Avoid direct identifiers and health data in `metadata`.

## Common responses

| Status | Meaning |
|---:|---|
| 200/201 | Request completed or event accepted |
| 401 | Missing or invalid token |
| 404 | Campaign, run, or artifact not found |
| 409 | Duplicate campaign slug or blocked artifact approval |
| 422 | Schema or enum validation failure |
| 503 | Required server-side token is not configured |
