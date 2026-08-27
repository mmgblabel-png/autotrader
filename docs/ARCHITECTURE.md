# WegMetDieKilos Campaign Automaton Architecture

**Author:** Manus AI  
**Status:** Implementation design  
**Target:** Local Python runtime and Railway

## 1. Design decision

The requested system must preserve the useful runtime behavior of Conway Automaton while replacing its sovereign-agent, blockchain, payment, replication, and unrestricted self-modification features with a marketing-specific, approval-gated workflow. Conway Automaton is MIT-licensed, and its public architecture describes a continuous agent loop, durable heartbeat scheduler, persistent memory, policies, skills, observability, model routing, self-modification, and replication.[1] The derivative will retain those architectural patterns but will not autonomously post, email, scrape personal data, buy services, create accounts, or modify production code.

| Approach | Tradeoffs | Cost | Setup Complexity |
|---|---|---:|---:|
| Full TypeScript fork of Conway Automaton | Maximum source similarity, but retains extensive Conway, wallet, on-chain identity, survival, and replication code that does not serve the PayPro campaign and increases operational and security risk. | High model and maintenance cost | High |
| **Marketing-specific Python adaptation in the selected repository** | Preserves the loop, heartbeat, memory, policies, audit trail, skills, metrics, and campaign-cloning concepts while remaining portable to the existing FastAPI/Railway project. This is the selected implementation. | Controlled by configurable model budgets | Medium |
| Lightweight content generator only | Fastest and cheapest, but lacks continuous optimization, durable scheduling, analytics, memory, audit history, and webhook integration. | Low | Low |

The second approach best matches the user’s selected repository and Railway target. Railway detects a root `Dockerfile`, injects `PORT`, and can gate activation on an HTTP 200 health check.[2] [3] Persistent state requires a volume because ordinary deployment storage is ephemeral.[4] Railway’s older `railway.json` format is deprecated and stops being read after 2026-12-01, so the project will include the current `.railway/railway.ts` format and retain a minimal legacy file only as a migration aid if necessary.[5]

## 2. Source-to-derivative feature map

| Conway Automaton capability | WegMetDieKilos derivative | Implementation rule |
|---|---|---|
| Think → Act → Observe loop | Research → SEO plan → content generation → compliance check → analytics → optimization proposal | Runs per campaign and persists every step |
| Heartbeat daemon | Durable scheduler for campaign refresh, analytics snapshots, retry handling, and stale-run recovery | Lease-based and idempotent; no overlapping runs |
| SQLite state | Campaigns, runs, artifacts, tracking events, memories, schedules, policies, budgets, and audit events | WAL mode locally; stored under `DATA_DIR` |
| Five-tier memory | Working notes, episodic run events, semantic campaign facts, reusable procedures, and channel/audience relationships | Retrieval is campaign-scoped and bounded |
| Policy engine | Anti-spam, consent, privacy, claims, affiliate disclosure, channel permissions, budget, and rate-limit rules | Every generated artifact and outbound-capable action is evaluated and logged |
| Skills | Reusable PayPro campaign skill with inputs, workflows, and templates | Packaged as a real `SKILL.md` and documented for copy/paste |
| Model router and spend tracker | Task-aware LLM model selection with per-run, hourly, and daily request/token budgets | Defaults to a cost-aware model; deterministic fallback for local tests |
| Observability | Structured JSON logs, counters, health status, scheduler history, and optimization metrics | Exposed through authenticated API endpoints where sensitive |
| Soul/constitution | Immutable brand and ethics policy plus editable campaign strategy | Guardrails cannot be changed through public endpoints |
| Self-modification | Optimization proposals only | A human must approve; production code is never rewritten automatically |
| Replication | Campaign cloning | Clones configuration and approved procedures, not infrastructure or autonomous agents |
| Social inbox | Signed or token-authenticated webhook/event intake | External content is treated as untrusted data and never as instructions |
| Wallet/on-chain identity | Removed | Not relevant to affiliate marketing and would add avoidable risk |
| Autonomous payments | Removed | No purchasing, billing, or fund transfer capability |

## 3. Runtime components

```text
FastAPI API
  ├─ Campaign endpoints
  ├─ Approval and artifact endpoints
  ├─ Click redirect + conversion event endpoints
  ├─ Webhook integration endpoints
  └─ Health, metrics, and scheduler status
            │
            ▼
CampaignOrchestrator
  ├─ ResearchAgent
  ├─ SEOAgent
  ├─ MarketingAgent
  └─ AnalyticsAgent
            │
            ▼
PolicyEngine → AffiliateLinkBuilder → ArtifactStore
            │
            ▼
SQLiteStore ← DurableHeartbeat → Metrics/Audit/Memory
            │
            ▼
LLMProvider (OpenAI-compatible or deterministic fallback)
```

The web service and background heartbeat run in one process by default. This avoids unsafe concurrent writes to a single SQLite file and fits Railway’s rule that one persistent volume is attached to one service; Railway also notes that services with attached volumes cannot use replicas.[6] A separate worker entry point is included for deployments that later migrate state to PostgreSQL, but it is disabled in the default Railway topology.

## 4. Agent contracts

| Agent | Inputs | Outputs | Dependencies |
|---|---|---|---|
| `ResearchAgent` | Product facts, target audience, market, channels, prior performance | Audience hypotheses, intent themes, keyword seed set, community research plan, source gaps, prohibited-claim reminders | Campaign memory and verified product facts |
| `SEOAgent` | Research brief, campaign goals, existing artifacts | Topic clusters, search intent, editorial calendar, internal-link plan, title/meta proposals | Research output |
| `MarketingAgent` | Product facts, research brief, SEO plan, brand policy, channel, CTA | Social posts, blog drafts, opt-in email drafts, landing-page copy, disclosure text | Research and SEO outputs |
| `AnalyticsAgent` | Clicks, attributed conversions, channel/campaign metadata, artifact versions | CTR/conversion summaries, evidence-based findings, experiment proposals, stop/continue recommendations | Tracking events and artifact history |

Each agent returns validated JSON. Outputs are stored as immutable artifact versions. Failed schema validation is retried once; persistent failures are recorded and surfaced instead of silently publishing incomplete content.

## 5. Campaign state machine

```text
draft → active → paused → archived
  │        │
  │        ├─ due heartbeat → queued → running → awaiting_approval
  │        │                                      │
  │        └──────────────── approved ←───────────┘
  │                                               │
  └──────────────────────────── rejected/revise ──┘
```

A campaign run is idempotent through an idempotency key derived from campaign, workflow, and scheduling window. Stale `running` records are recovered by the heartbeat. Public requests cannot activate a campaign, approve an artifact, or trigger model spending without the control token.

## 6. Ethical and legal operating model

> The runtime generates value-first marketing assets and opt-in workflow recommendations. It never scrapes or purchases personal contact data, sends unsolicited messages, impersonates people, fabricates testimonials, guarantees weight-loss results, or bypasses platform restrictions.

The supplied PayPro URL currently redirects to a quiz page positioning the product as an app for losing weight in a healthy way with a personalized plan based on age.[7] That page does not verify exact outcomes, pricing, medical efficacy, or detailed Bronze Plan features. Therefore, generated copy must distinguish supplied facts from assumptions, avoid unverified specifics, include affiliate disclosure where appropriate, and use realistic language such as “kan helpen” rather than guaranteed outcomes.

| Policy area | Enforcement |
|---|---|
| Consent | Email assets are labeled for opt-in audiences only; no sending integration is enabled by default |
| Privacy | Tracking endpoints accept pseudonymous event IDs and campaign metadata; raw personal profiles are rejected |
| Claims | Block guaranteed, rapid, effortless, medical, before/after, and unsupported numerical weight-loss claims |
| Affiliate transparency | Every sales-oriented artifact includes a configurable affiliate disclosure |
| Platform rules | Default mode is `draft_only`; publishing requires a separately approved connector and human confirmation |
| Frequency | Per-campaign generation and webhook rate limits prevent runaway activity |
| Auditability | Policy decisions, model calls, state changes, approvals, and events are append-only |

## 7. Affiliate link strategy

`PAYPRO_PRODUCT_URL` is treated as the canonical destination. `PAYPRO_AFFILIATE_ID` is required for operator completeness but is not blindly appended using an undocumented parameter. If `PAYPRO_AFFILIATE_URL_TEMPLATE` contains `{affiliate_id}`, the runtime substitutes the configured ID. Otherwise it preserves the supplied product URL and adds only standard campaign attribution parameters (`utm_source`, `utm_medium`, `utm_campaign`, `utm_content`) through the internal redirect endpoint.

Generated content uses the application tracking URL:

```text
https://<service-domain>/r/<campaign-slug>?src=<channel>&content=<artifact-id>
```

The redirect records a click event and returns HTTP 302 to the resolved PayPro target. Conversions can be recorded through a token-protected webhook when PayPro or another analytics tool can provide a suitable callback. No webhook capability is assumed without operator confirmation and provider documentation.

## 8. Deployment topology

| Component | Default Railway deployment | Persistence |
|---|---|---|
| API + heartbeat | One always-on service from the root Dockerfile | `/data` volume |
| SQLite database | `${DATA_DIR}/campaign_automaton.db` | Railway volume |
| Artifacts | SQLite JSON/text plus optional filesystem export | Railway volume |
| Secrets | Railway service variables | Never committed |
| Health check | `/api/health` | Returns 200 only after DB and heartbeat initialization |

The container listens on Railway’s injected `PORT` variable.[3] The deployment uses one replica because Railway volumes cannot be mounted to replicas and overlapping deployments are restricted to protect data integrity.[6] The Docker image runs as a non-root application user locally; operators who encounter volume permissions can follow Railway’s documented volume guidance rather than embedding secrets or broad permissions in the image.

## 9. Security controls

The API separates public tracking endpoints from protected control endpoints. Control and webhook secrets are compared with constant-time comparison. CORS defaults to local development only. Request bodies are size-bounded through schemas, user-supplied URLs are validated, external webhook content is treated as data, and prompt construction places external values inside explicit untrusted-data boundaries. The runtime has no shell tool, filesystem mutation tool, browser automation, autonomous posting connector, or payment capability.

## 10. References

[1]: https://github.com/Conway-Research/automaton "Conway Research — Automaton"
[2]: https://docs.railway.com/builds/dockerfiles "Railway Docs — Dockerfiles"
[3]: https://docs.railway.com/deployments/healthchecks "Railway Docs — Healthchecks"
[4]: https://docs.railway.com/deployments/reference "Railway Docs — Deployments reference"
[5]: https://docs.railway.com/infrastructure-as-code "Railway Docs — Infrastructure as Code"
[6]: https://docs.railway.com/volumes/reference "Railway Docs — Volumes"
[7]: https://www.paypro.nl/producten/WegMetDieKilos_Bronze_Plan/114766/183297 "PayPro product URL supplied by user"
