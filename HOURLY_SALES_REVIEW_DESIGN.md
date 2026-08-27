# Hourly Sales Review Agent — Design

**Branch baseline:** `feat/paypro-campaign-automaton`
**Purpose:** Add a second, deterministic internal agent that records one hourly review of campaign health, measurable funnel movement, content readiness, and the next owner-review task.  It will **not** create, edit, approve, publish, send, spend, scrape, or claim a sale.

## Scope and safety boundary

The review is a scheduled internal analytics artifact.  It has no LLM call and therefore does not consume model requests.  It does not inspect personal data, because it reads only the existing campaign-level aggregate metrics.  It runs after the existing heartbeat acquires its global lease and will never queue or execute a campaign workflow.  Existing `DRAFT_ONLY`, affiliate-disclosure, consent, and human-confirmation policy controls remain unchanged.

| Capability | Included | Excluded |
|---|---:|---:|
| Durable hourly review rows in SQLite | Yes | Raw visitor/event metadata |
| Hour-over-hour funnel deltas | Yes | Invented traffic or sales |
| Deterministic next-step recommendation | Yes | Auto-applied optimisation |
| Content readiness counts | Yes | Artifact approval or publication |
| Owner-only API report retrieval | Yes | Public reporting endpoint |
| Scheduler invocation | Yes, opt-in | New external cron, outbound calls, or campaign runs |

## Data model

A new `hourly_sales_reviews` table will contain one row per campaign per UTC hour.  Its uniqueness key `(campaign_id, hour_bucket)` makes the job idempotent, even if the heartbeat is called repeatedly or the process restarts.  Each review stores a JSON snapshot of aggregate metrics and a JSON recommendation.  The review record does not contain affiliate URLs, secrets, draft content, direct identifiers, health data, raw webhook payloads, or model output.

```text
hourly_sales_reviews
  id                 primary key
  campaign_id        foreign key to campaigns
  hour_bucket        UTC YYYY-MM-DDTHH:00:00+00:00
  metrics_json       cumulative and prior-hour aggregate counters
  readiness_json     content/data-quality/attribution readiness flags
  recommendation_json one deterministic next action and owner gate
  created_at         UTC timestamp
  unique(campaign_id, hour_bucket)
```

## Hourly review algorithm

Each heartbeat checks whether `HOURLY_SALES_REVIEW_ENABLED=true`.  When enabled, it creates a review only for campaigns in `active` status.  It calculates cumulative views, clicks, signups, conversions, click-through rate, conversion rate, and change since the prior stored review.  Sources labelled `railway-live-verification`, `website-live-verification`, or `internal-verification` do not count as observed customer traffic.  This prevents technical checks from being mistaken for sales evidence.

The recommendation has a strict hierarchy: first repair an attribution/readiness gap; then collect a small amount of real, consent-respecting traffic through one already-approved asset; then inspect click quality; then, only after sufficient observed views/clicks, propose one reversible owner-reviewed experiment.  The report states that a conversion is not present unless a verified `paypro` conversion callback has been recorded.

## Configuration and API

| Setting or endpoint | Default / access | Effect |
|---|---|---|
| `HOURLY_SALES_REVIEW_ENABLED` | `false` | Explicitly enables local hourly review records when set to `true`. |
| `GET /api/campaigns/{slug}/hourly-reviews` | Owner token required | Lists the campaign’s durable review history. |
| `GET /api/campaigns/{slug}/hourly-reviews/latest` | Owner token required | Returns the newest review or `404` before the first review. |
| Heartbeat details | Public health has aggregate status only | Includes count of reviews created, never contents or secrets. |

## Validation plan

The implementation must test that: disabled mode makes no database change; a matching hour is created once only; the next hour creates exactly one successor; verification-only traffic is labelled as such; a real conversion cannot be inferred from a click; the owner endpoint rejects unauthenticated requests; and the existing test/lint/compile suites still pass.  A local, deterministic run is the only appropriate first test.  Deploying the change, toggling the opt-in setting, creating a campaign run, or publishing a draft requires separate confirmation.
