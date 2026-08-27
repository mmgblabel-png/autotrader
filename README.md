# Amazon Associate Campaign Automaton

**Amazon Associate Campaign Automaton** is an approval-gated campaign workflow for researching products, preparing fact-based affiliate drafts, recording pseudonymous first-party events, and evaluating controlled tests. It is adapted from the structural ideas in [Conway Research’s Automaton][1], but deliberately removes autonomous purchasing, unapproved publishing, link cloaking, and uncontrolled self-modification.

> The application creates drafts, research plans, SEO plans, analytics reports, and reversible optimization proposals. It does **not** make purchases, publish to third-party accounts, scrape profiles, contact people without consent, guarantee conversion, or create Amazon affiliate links automatically.

The current default campaign is an evidence-informed **draft test** for the Owala FreeSip 24 oz water bottle. It is **not** a claim that this product will convert fastest. The linked US Associates account reported zero clicks, ordered items, shipped items, commissions, and bounties for the last 30 days reviewed on 27 August 2026. A product-level conversion claim would therefore be unsupported until controlled test data exists.

## Product selection and test rationale

The default test candidate was selected from the Amazon.com Home & Kitchen best-seller page, then checked on its own product detail page. At review time it had a mid-range listed price, substantial public social proof, a clearly understood use case, and product facts that can be described without health, medical, or performance promises. Its Associates SiteStripe category was displayed as **Kitchen & Dining** with a **4.5%** commission rate. Those dynamic values, along with ratings, reviews, ranking, stock, price, delivery, and commission rate, are deliberately excluded from generated public copy because they can change and may require an approved Amazon data source for reuse.[2] [3]

| Factor | Why it supports an initial test | Guardrail |
|---|---|---|
| Everyday purchase intent | A reusable bottle has a familiar, practical use case for commuting, campus, work, gym, and daily routines. | Content must not claim hydration, health, fitness, or productivity outcomes. |
| Moderate price point | A lower-commitment purchase can be suitable for a first CTA test. | Never hard-code the price, deal, discount, or stock claim in public copy. |
| Product-specific facts | The product page describes capacity, materials, lid, carry loop, cleaning opening, and cupholder caveat. | Use only verified facts and include the cupholder limitation. |
| Current account evidence | The account had no historical conversion data. | Treat the first campaign as a measurement exercise, not an earnings prediction. |
| Market fit | The selected item was unavailable for the current Netherlands delivery location, while the account tag was for the US store. | Initial content is restricted to US-based traffic that can shop Amazon.com. |

The initial direct alternatives worth testing *after* the Owala baseline are an urgent household-problem product (such as ant or flying-insect control) and a familiar replenishment product (such as body lotion). Each needs a separate audience, product verification, exact Associates link, and one-variable experiment. Do not place unrelated products together merely to increase clicks.

## Amazon-specific compliance design

Amazon requires Associates to use the special tagged link formats it provides and to clearly and prominently identify themselves as an Associate.[4] Its Participation Requirements also prohibit cloaking, hiding, spoofing, or otherwise obscuring the URL of a site containing Special Links, including by using a redirecting page.[5]

Accordingly, this branch implements the following constraints.

| Requirement | Implementation |
|---|---|
| Direct Special Link | `AMAZON_ASSOCIATE_URL` must contain the exact tagged Amazon URL or `amzn.to` URL copied from SiteStripe or Associates Central. The application never fabricates tags. |
| No link rewriting | The workflow does not append UTM parameters, wrap, shorten, cloak, or redirect an Amazon Special Link. |
| No internal redirect | The legacy `/r/<campaign>` endpoint returns `410 Gone` while `AFFILIATE_PROVIDER=amazon`. |
| Prominent disclosure | Generated Amazon CTA copy places `Disclosure: As an Amazon Associate I earn from qualifying purchases. (paid link)` immediately beside the link. |
| Draft-first operation | A missing Special Link blocks marketing artifacts from approval. `DRAFT_ONLY=true` blocks outbound publication even after a link is configured. |
| Conservative facts | Policy checks block copied customer review/rating claims, outcome promises, email/DM spam, sensitive-data abuse, and redirect/cloaking risk. |
| Human control | Every artifact begins as a draft; a person must verify facts, disclosure, link, channel rules, and approval before any external publishing. |

Amazon states that a standard qualifying session generally ends after 24 hours, when an order is placed, or when another Associate’s Special Link is clicked; cart additions can have a longer qualification window subject to the program rules.[6] This is an attribution rule, not a reason to use pressure tactics, automatic redirects, or incentives. Amazon’s rules also bar ordering on behalf of another person, artificially generating clicks, and using Amazon marks in prohibited paid-search placements.[5]

## Architecture

```text
FastAPI control plane and optional read-only public site
                         │
                         ▼
               CampaignOrchestrator
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
 ResearchAgent       SEOAgent       MarketingAgent
        └────────────────┼────────────────┘
                         ▼
                   AnalyticsAgent
                         │
                         ▼
         PolicyEngine → Direct Amazon Special Link
                         │
                         ▼
 SQLiteStore ← HeartbeatScheduler → Audit / Metrics / Memory
                         │
                         ▼
 OpenAI-compatible LLM or deterministic fallback
```

The four-agent sequence is **Research → SEO → Marketing → Analytics**. Every run, artifact version, policy finding, event, memory entry, model call, approval, and scheduler heartbeat is retained in SQLite. The public site is optional and renders only artifacts that are both policy-cleared and owner-approved.

| Agent | Role | Typical output |
|---|---|---|
| `ResearchAgent` | Defines audience segments, intent themes, public-source research needs, and assumptions. | Research brief and source gaps. |
| `SEOAgent` | Converts research into helpful topic clusters and a search-intent plan. | Editorial and metadata guidance. |
| `MarketingAgent` | Prepares factual, channel-specific product-research drafts. | Blog, opt-in email, social, landing-page, and community-response drafts. |
| `AnalyticsAgent` | Explains measured signals and proposes one reversible test at a time. | Uncertainty statement, experiment proposal, and stop/continue criteria. |

## Repository structure

```text
.
├── campaign_automaton/
│   ├── agents/                  # Research, SEO, marketing, and analytics agents
│   ├── api.py                   # FastAPI control surface and guarded legacy endpoints
│   ├── config.py                # Provider-aware environment configuration
│   ├── links.py                 # Direct Special Link enforcement
│   ├── policy.py                # Claims, disclosure, anti-spam, and Amazon policy gates
│   ├── publisher.py             # Read-only, owner-approved public rendering
│   ├── runtime.py               # Bootstrap and campaign seeding
│   ├── scheduler.py             # Lease-protected heartbeat
│   └── store.py                 # SQLite persistence, metrics, audit, and memory
├── config/campaign.yaml         # Active Owala draft-campaign configuration
├── research_notes.md            # Account baseline, product review, and source notes
├── tests/                       # Core and API regression tests
├── .env.example                 # Safe default configuration
└── pyproject.toml               # Package metadata and development dependencies
```

## Quickstart

Python 3.11 or later is required. The following local workflow validates the application without generating external content or publishing anything.

```bash
git clone https://github.com/mmgblabel-png/autotrader.git amazon-associate-campaign-automaton
cd amazon-associate-campaign-automaton
git switch autoamazonsale

python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit only the values described below.
set -a; . ./.env; set +a

# Validate deterministic, draft-only operation.
python -m campaign_automaton init
python -m campaign_automaton run \
  --campaign owala-freesip-24oz \
  --workflow full_campaign \
  --force
python -m campaign_automaton artifacts \
  --campaign owala-freesip-24oz
```

Start the API and heartbeat locally:

```bash
python -m campaign_automaton serve --port 8000
curl http://localhost:8000/api/health
```

## Configuration

Copy `.env.example` to `.env`. Do not commit `.env`, database files, reports, exports, secrets, or copied Associates links.

```dotenv
AFFILIATE_PROVIDER=amazon
AMAZON_PRODUCT_URL=https://www.amazon.com/dp/B0BZYCJK89
AMAZON_ASSOCIATE_URL=
AFFILIATE_DISCLOSURE="Disclosure: As an Amazon Associate I earn from qualifying purchases. (paid link)"
DRAFT_ONLY=true
WEBSITE_ENABLED=false
AUTO_RUN_DUE_CAMPAIGNS=false
```

The canonical `AMAZON_PRODUCT_URL` is a factual reference only. Before a product CTA can be approved, copy the **exact** URL from Amazon Associates SiteStripe or Associates Central and place it in `AMAZON_ASSOCIATE_URL`. Do not manually add an Associate tag; do not append UTM values; do not pass the link through a redirect; and do not use a generic product URL in its place.

| Variable | Initial value | Meaning |
|---|---:|---|
| `AMAZON_ASSOCIATE_URL` | Empty | Deliberately blocks approvals until an owner pastes a valid Special Link. |
| `DRAFT_ONLY` | `true` | Blocks all external publishing actions. |
| `WEBSITE_ENABLED` | `false` | Keeps public pages inaccessible. |
| `AUTO_RUN_DUE_CAMPAIGNS` | `false` | Avoids unattended model runs during setup. |
| `LLM_PROVIDER` | `deterministic` | Runs no-cost predictable test drafts. |
| `CONTROL_TOKEN` | Unique secret | Protects owner control endpoints. |
| `WEBHOOK_TOKEN` | Different unique secret | Protects manually integrated event ingestion. |

Generate separate tokens with `openssl rand -hex 32`. The legacy PayPro configuration fields remain only for backward compatibility and are ignored when `AFFILIATE_PROVIDER=amazon`.

## Required owner review before publishing

The workflow is intentionally unable to publish directly. Before any outside use of an artifact, the owner must verify the table below.

| Review item | Required check |
|---|---|
| Associate link | It is the exact link copied from the Associates interface, remains unmodified, and leads to the relevant Amazon product page. |
| Disclosure | The mandated Associate statement and a clear link-level disclosure are visible in the same medium, close to the CTA. |
| Facts | Product facts match the current listing; variable price, rank, rating, stock, discount, delivery, and review language are absent unless used through an approved Amazon source. |
| Market | The audience can use the target Amazon storefront and reasonably purchase the product. |
| Channel rules | The destination channel permits affiliate promotion and the content is adapted to its rules. |
| Consent | Email is opt-in with an unsubscribe path; community content responds to a relevant question and follows community rules. |
| Claims | No health, medical, fitness, productivity, scarcity, guarantee, or invented testimonial claim is present. |

Artifacts can be inspected and approved through the CLI after this review.

```bash
python -m campaign_automaton artifacts --campaign owala-freesip-24oz
python -m campaign_automaton review <artifact-id> \
  --decision approved \
  --reviewer owner \
  --notes "Exact Special Link, disclosure, source facts, and channel rules verified"
```

Approving an artifact changes its stored review state. It does not post content, send email, create a purchase, or activate the public website.

## Measuring the first conversion test

Because the current account has no historical conversion data, use a small, controlled test rather than choosing a product based on rank alone. Test one product/audience/content angle at a time, establish the audience and channel before publishing, and evaluate Amazon reporting only after a predeclared observation window.

| Metric | System of record | Interpretation |
|---|---|---|
| Content views / click intent | First-party aggregated events | Measures whether the content and CTA are being seen and considered. It does not prove Amazon referral or purchase. |
| Clicks, ordered items, shipped revenue, conversion, earnings | Amazon Associates reports | Use as the authoritative source for Amazon performance. |
| Earnings per click | Calculated from reporting after sufficient volume | Useful only once a comparable number of clicks exists. |
| Return / cancellation signal | Amazon reporting where available | Avoid declaring a winner based solely on early orders. |

The current API retains manual, pseudonymous event ingestion for owner-approved integrations. It does **not** fabricate Amazon conversion webhooks, and `/api/webhooks/paypro` is disabled with `410 Gone` in Amazon mode. Do not upload or store customer account credentials, names, email addresses, IP addresses, or other direct identifiers.

## API examples

Owner endpoints require `X-Control-Token`.

```bash
export BASE=http://localhost:8000
export CONTROL_TOKEN='your-secret'

curl -H "X-Control-Token: $CONTROL_TOKEN" "$BASE/api/config/status"
curl -H "X-Control-Token: $CONTROL_TOKEN" "$BASE/api/campaigns"

curl -X POST "$BASE/api/campaigns/owala-freesip-24oz/runs" \
  -H "Content-Type: application/json" \
  -H "X-Control-Token: $CONTROL_TOKEN" \
  -H "Idempotency-Key: owala-content-2026-35" \
  -d '{"workflow":"content","channels":["blog","social"],"force":false}'

curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/campaigns/owala-freesip-24oz/artifacts"
```

The public site remains disabled until `WEBSITE_ENABLED=true`. When enabled, it renders only approved, policy-cleared artifacts at `/site/owala-freesip-24oz`; its Amazon CTA is a direct Special Link with a disclosure, never a first-party redirect.

## Scheduler behavior

The heartbeat uses a database lease to prevent overlapping work. It recovers stale runs, executes queued work, optionally generates due drafts for active campaigns, calculates the next cron occurrence, and records its history. Keep `AUTO_RUN_DUE_CAMPAIGNS=false` through the first manual content and compliance review.

| Setting | Default | Meaning |
|---|---:|---|
| `HEARTBEAT_ENABLED` | `true` | Starts a background heartbeat with the API. |
| `HEARTBEAT_INTERVAL_SECONDS` | `30` | Minimum tick delay. |
| `AUTO_RUN_DUE_CAMPAIGNS` | `false` | Prevents automatic future content-generation runs. |
| Campaign `schedule_cron` | `0 9 * * 1` | Monday 09:00 review/draft schedule, should the owner enable it later. |

Run only one SQLite-backed service instance. For durable deployment, use persistent storage and a single writer, or migrate the storage/queue design before scaling horizontally.

## Testing

The branch includes direct-link, disclosure, policy, API, scheduler, event-deduplication, and public-rendering tests.

```bash
python -m pytest -q
ruff check .
```

## References

[1]: https://github.com/Conway-Research/automaton "Conway Research — Automaton"
[2]: https://www.amazon.com/Best-Sellers-Home-Kitchen/zgbs/home-garden "Amazon Best Sellers — Home & Kitchen"
[3]: https://www.amazon.com/Owala-FreeSip-Insulated-Stainless-BPA-Free/dp/B0BZYCJK89 "Amazon — Owala FreeSip Stainless Steel Water Bottle 24 oz"
[4]: https://affiliate-program.amazon.com/help/operating/agreement "Amazon Associates Program Operating Agreement"
[5]: https://affiliate-program.amazon.com/help/operating/participation/ "Amazon Associates Program Participation Requirements"
[6]: https://affiliate-program.amazon.com/help/operating/policies "Amazon Associates Program Policies"
[7]: https://affiliate-program.amazon.com/help/node/topic/GHQNZAU6669EZS98 "Amazon Associates — Disclosure guidance"
