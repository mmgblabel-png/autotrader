# Sales Readiness Council — Ten-Agent Design

**Scope:** Add ten deterministic advisory agents to the existing hourly review. They share one sanitized, aggregate campaign context and feed their findings to the existing `HourlySalesReviewer`, which stores one private report per campaign per UTC hour. No agent invokes a model, accesses external accounts, handles personal data, creates content, approves artifacts, publishes, sends outreach, buys traffic, or guarantees a sale.

## Collaboration sequence

The council uses a bounded, one-way evidence pipeline. Every finding includes a status, reason, aggregate evidence, and prerequisite findings. A later agent may read only prior findings and the sanitized context. This makes the reasoning traceable and prevents a loop in which agents recursively create new work.

```text
Aggregate metrics + artifact metadata + campaign facts
  │
  ├─ 1. Measurement Integrity ─┐
  ├─ 2. Funnel Stage ──────────┤
  ├─ 3. Attribution Integrity ─┤
  ├─ 4. Offer Facts ───────────┤
  ├─ 5. Audience Definition ───┤
  ├─ 6. Content Readiness ─────┤
  ├─ 7. Landing-Page Readiness ┤──► 10. Experiment Guardrail
  ├─ 8. Consent & Claims ──────┤                 │
  └─ 9. Acquisition Handoff ───┘                 ▼
                          Existing HourlySalesReviewer
                                      │
                                      ▼
                         One owner-review recommendation
```

## Agent contracts

| # | Advisory agent | Reads | Produces | Never does |
|---:|---|---|---|---|
| 1 | Measurement Integrity | Aggregate event sources and counts | Labels evidence as none, verification-only, or observed. | Count a technical check as customer demand. |
| 2 | Funnel Stage | Sanitized funnel totals plus Agent 1 | Identifies the earliest unproven funnel stage. | Infer a signup or sale. |
| 3 | Attribution Integrity | Verified conversion count, campaign configuration status | Flags that account-issued affiliate attribution still needs owner verification. | Guess an affiliate format, ID, or commission. |
| 4 | Offer Facts | Public product-fact count | Flags missing or sparse verified facts. | Invent efficacy, price, or product details. |
| 5 | Audience Definition | Campaign audience and goals | Flags missing audience/intent definition. | Profile, scrape, or acquire people. |
| 6 | Content Readiness | Artifact statuses and policy summaries | Reports draft/approved/blocked counts. | Alter, approve, or publish an artifact. |
| 7 | Landing-Page Readiness | Approved artifact types only | Identifies whether a reviewed landing asset exists. | Change a public page. |
| 8 | Consent & Claims | Policy-finding counts and draft-only state | Flags blocked content and preserves human-review boundary. | Send email/DM or weaken policy. |
| 9 | Acquisition Handoff | Agents 1, 3, 6, 7, 8 | States whether a manual, owner-approved handoff can be prepared. | Select a channel, post, send, or spend. |
| 10 | Experiment Guardrail | Agents 1, 2, 6, 9 and evidence thresholds | Allows only a proposal for one reversible test when evidence is sufficient. | Apply an experiment automatically. |

## Data boundary

The shared context excludes affiliate URLs/IDs, control and webhook tokens, raw event metadata, visitor identifiers, health information, artifact text, and model prompts/responses. Advisor output is stored inside the existing private hourly-review JSON record, not exposed through the public portfolio endpoint.

## Hourly behavior

The existing heartbeat remains the only scheduler. If `HOURLY_SALES_REVIEW_ENABLED=false`, it creates no council report. If true, each active campaign receives a maximum of one report per UTC hour under the existing unique `(campaign_id, hour_bucket)` constraint. The scheduler will not run a campaign workflow as part of the council feature.

## Production activation conditions

Implementation can be tested locally without activation. Before the setting is changed in Railway, the associated pull requests must be reviewed/merged, the production health endpoint must remain healthy, the persistent SQLite volume must be present, and the owner must explicitly approve changing `HOURLY_SALES_REVIEW_ENABLED` to `true`. No public or paid marketing action follows from that configuration change.
