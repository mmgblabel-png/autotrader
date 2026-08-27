# Hourly Sales-Readiness Audit

**Audited branch:** `feat/paypro-campaign-automaton` at `b9ffb8d5b30c56124a04c1ea3b17eafd9513248c`
**Audit date:** 27 August 2026
**Scope:** Read-only repository review and public endpoint verification. No content was published, no campaign was edited, no message was sent, and no paid traffic or affiliate-account setting was changed.

## Executive assessment

The branch is a well-structured, approval-gated affiliate-campaign runtime rather than an autonomous sales bot. It already generates drafts and research/SEO/analytics plans, stores campaign state in SQLite, tracks first-party redirects, accepts separately authenticated conversion events, and prevents unapproved outreach. The production service is healthy and the owner-approved public portfolio is reachable. However, it has **not yet produced evidence of real audience traffic or a sale**. The aggregated public snapshot contains only labelled verification events and records zero signups and zero conversions. It would be misleading to treat the current test clicks as customer demand.

| Area | Verified current state | Readiness implication |
|---|---|---|
| Production runtime | Health endpoint reports production, SQLite healthy, heartbeat running every 30 seconds, and no recent scheduler error. | Stable enough to host a read-only reporting loop. |
| Public website | `/site` is live with three owner-approved campaign pages and transparent affiliate wording. | A policy-cleared destination exists for future approved traffic. |
| Content safety | The policy blocks unsupported health/weight-loss claims, spam, profile scraping, bought lists, unsolicited messages, and hidden affiliate disclosures. | Keep these constraints; they protect both visitors and the campaign. |
| Draft and approval model | The orchestrator stores artifacts and optimisation proposals, with explicit review gates. | Suitable for a second agent that proposes, but never publishes, changes. |
| Measurement | Public snapshot: 1 view, 4 clicks, 0 signups, 0 conversions; all counted sources are verification-only. | No meaningful conversion conclusion can be drawn. |
| Reporting | Public portfolio snapshot refreshes while a page is open, but no durable hourly owner report exists. | The requested hourly report is the primary missing feature. |
| Campaign cadence | Heartbeat runs every 30 seconds; active campaigns are scheduled daily at 00:00 CEST. | This is not an hourly sales-review cadence. |
| Affiliate attribution | The branch deliberately refuses to guess PayPro’s account-specific affiliate URL format. | Confirm the account-provided affiliate URL template before treating external clicks as commission-attributed. |

## Current live evidence

At the time of verification, `GET /api/health` returned `200 OK`, `draft_only:false`, `llm_mode:"deterministic"`, and a healthy scheduler. `GET /api/public/farm-snapshot` reported `data_quality:"verification_only"` and zero signups/conversions across the three active campaigns. Its own evidence threshold is 100 views and 20 clicks per campaign; progress was 0% and `strategy_change_allowed` was false. The public `/site` page loads a portfolio of owner-approved offerings only.

> **Interpretation:** The technical delivery and first-party tracking route are working, but the system has no observed customer traffic on which to optimise. The next job is to establish reliable, consent-respecting measurement and an owner-reviewed acquisition plan—not to multiply content or claim an imminent sale.

## Recommended hourly second-agent role

The second agent should run one durable **hourly internal review**. It must calculate deltas from locally stored facts, capture campaign/heartbeat health, list drafts waiting for review, flag data quality, and produce at most one reversible recommendation per campaign. It should neither generate unlimited new campaigns nor repeat work recursively. A run should be idempotent for the same UTC-hour and use the scheduler’s existing lease semantics.

| Report section | Data source | Allowed agent action | Explicitly excluded |
|---|---|---|---|
| Runtime status | Heartbeat history and API health | Flag a scheduler/database error. | Restart, deploy, or reconfigure a service. |
| Funnel metrics | First-party views, clicks, signups, verified conversions | Calculate deltas and label data quality. | Invent a visitor, signup, sale, or attribution. |
| Content readiness | Draft/approved artifacts and policy findings | Identify one owner-review item. | Auto-approve or publish an artifact. |
| Experiment queue | Existing optimisation proposals and sufficient-evidence state | Recommend one reversible test with a stop rule. | Change production content automatically. |
| Affiliate readiness | Configuration status only | Flag missing/non-ready attribution configuration. | Guess, replace, or expose an affiliate URL/ID. |

## Prioritised path toward the first attributable sale

The aim should be a measurable, compliant first **attributable** conversion, not a promised sale. The first three steps are internal improvements: create durable hourly reports, make every approved traffic source use a unique first-party tracking link, and verify that the PayPro account-issued destination/template is correct. The next step is to select one owner-approved, consent-respecting acquisition channel and manually approve exactly one piece of content or distribution action for that channel. The reporting agent should then measure source, content identifier, click-through, signup, and verified conversion signals before proposing a single reversible iteration.

Do not infer causality from the current four verification clicks. Do not modify the three live pages in response to those events. The repository’s own analytics guardrail requires more observed evidence before it recommends a strategy change.

## Implementation backlog

| Priority | Improvement | Result | Approval boundary |
|---|---|---|---|
| P0 | Add an `HourlySalesReview` data model, SQLite report table, idempotent hourly scheduler job, and owner-only report endpoint. | A durable hourly record of movement, readiness, and one proposed next step. | No external action. |
| P0 | Surface an owner-only dashboard/report view with a simple funnel, data-quality badge, and backlog. | Reports can be reviewed without exposing campaign configuration or drafts publicly. | Deployment review required if published. |
| P1 | Add real-vs-verification traffic segmentation and hour-over-hour deltas. | Prevents test events from being mistaken for customer acquisition. | No external action. |
| P1 | Add a pre-publication attribution checklist to the owner report. | Flags missing exact affiliate template or unverified destination. | Owner must supply/approve account-specific details. |
| P2 | Provide an approved-content handoff pack: a policy-cleared draft, a unique tracker link, disclosure, and a manual channel checklist. | Supports a transparent manual first distribution test. | User must explicitly approve any public posting, email, outreach, or paid spend. |
| P2 | Ingest verified conversion callbacks once the account can provide a documented callback method. | Closes the loop between a tracked click and an attributable conversion. | Requires account-level integration and secret configuration. |

## Evidence and references

[1] [Branch pull request #6](https://github.com/mmgblabel-png/autotrader/pull/6)

[2] [Live service health](https://web-production-61a287.up.railway.app/api/health)

[3] [Public aggregate campaign snapshot](https://web-production-61a287.up.railway.app/api/public/farm-snapshot)

[4] [Public owner-approved portfolio](https://web-production-61a287.up.railway.app/site)
