# WegMetDieKilos PayPro Campaign Automaton

**WegMetDieKilos PayPro Campaign Automaton** is an approval-gated AI campaign runtime adapted from the architectural ideas in [Conway Research’s Automaton](https://github.com/Conway-Research/automaton). It preserves the useful continuous-loop, heartbeat, persistent-memory, policy, skills, audit, observability, and optimization patterns while replacing wallet, autonomous payment, infrastructure replication, and unrestricted self-modification with safe affiliate campaign workflows.[1]

> The application creates drafts, research plans, SEO plans, analytics reports, and optimization proposals. Its optional self-hosted website renders only owner-approved, policy-cleared artifacts after an explicit website opt-in. It does **not** send unsolicited messages, scrape personal profiles, purchase leads, publish through third-party accounts autonomously, make medical claims, or guarantee weight-loss outcomes.

## What is implemented

The runtime coordinates four specialized agents in a durable **Research → SEO → Marketing → Analytics** workflow. Every run, artifact version, policy finding, click, conversion, memory, model call, approval, and scheduler event is stored in SQLite. A tracked redirect records clicks before sending the visitor to the configured PayPro destination.

| Capability | Implementation |
|---|---|
| Continuous agent workflow | Ordered four-agent campaign runs with structured outputs |
| Durable heartbeat | Lease-protected, non-overlapping background scheduler |
| Five-tier-inspired memory | Working context, episodic events, semantic facts, procedures, and channel/audience context |
| Policy engine | Anti-spam, consent, privacy, responsible claims, affiliate disclosure, rate and approval gates |
| Skills | Installable `paypro-campaign-automaton` skill in `skill/` |
| Model routing | OpenAI-compatible client with `gpt-5-mini`, `gpt-5-nano` fallback, and request budgets |
| Offline operation | Deterministic no-cost content fallback when no model API key is configured |
| Observability | Health, scheduler status, structured logs, audit records, run summaries, and analytics |
| Self-improvement | Reversible optimization proposals that require human approval |
| Replication equivalent | Safe campaign cloning rather than autonomous infrastructure creation |
| Railway deployment | Root Dockerfile, current `.railway/railway.ts`, persistent volume, and health check |

The supplied PayPro product URL currently redirects to a WegMetDieKilos quiz page that describes an app for losing weight in a healthy way and a personalized starting point based on age.[2] The repository treats those visible statements as verified facts and leaves pricing, exact Bronze Plan contents, numerical outcomes, and medical efficacy unverified.

## Architecture

```text
FastAPI control plane and public tracking redirect
                 │
                 ▼
        CampaignOrchestrator
       ┌─────────┼─────────┐
       ▼         ▼         ▼
 ResearchAgent  SEOAgent  MarketingAgent
       └─────────┬─────────┘
                 ▼
          AnalyticsAgent
                 │
                 ▼
 PolicyEngine → AffiliateLinkBuilder → Versioned Artifacts
                 │
                 ▼
 SQLiteStore ← HeartbeatScheduler → Audit / Metrics / Memory
                 │
                 ▼
 OpenAI-compatible LLM or deterministic fallback
```

The default deployment runs the web API and heartbeat in one process. This is deliberate: Railway volumes attach to one service and cannot be used with replicas, so one process avoids concurrent SQLite writers and preserves a simple operational model.[3]

## Agent roles

Each agent receives only campaign facts, prior-agent outputs, bounded campaign memory, and pseudonymous analytics. External webhook text is treated as untrusted data, never as system instructions.

| Agent | Goal | Inputs | Outputs |
|---|---|---|---|
| `ResearchAgent` | Find useful audience, keyword, community, and competitor research directions | Product facts, market, audience, prior memory | Segments, intent themes, keyword seeds, public-source research plan, source gaps |
| `SEOAgent` | Turn research into helpful search content | Research brief, goals, channels | Topic clusters, search intent, editorial calendar, metadata and internal-link guidance |
| `MarketingAgent` | Create responsible channel-specific Dutch drafts | Research, SEO, verified facts, tracked link, disclosure | Blog, opt-in email, social, landing-page, and community-response drafts |
| `AnalyticsAgent` | Explain measured results and propose safe tests | Views, clicks, signups, conversions, channel metadata | Rates, uncertainty statement, one-variable experiment proposal, stop/continue guardrails |

The agent sequence is encoded in `campaign_automaton/orchestrator.py`. Real model outputs must match a strict JSON schema. If the model endpoint fails, the run continues with visible deterministic fallback content rather than silently fabricating a successful model call.

## Repository structure

```text
.
├── .railway/
│   ├── railway.ts               # Current Railway project-level IaC
│   └── README.md                # Plan/apply and secret setup
├── campaign_automaton/
│   ├── agents/                  # Research, SEO, Marketing, Analytics
│   ├── api.py                   # FastAPI endpoints and tracked redirect
│   ├── cli.py                   # Owner CLI
│   ├── config.py                # Environment configuration
│   ├── links.py                 # PayPro destination and UTM builder
│   ├── llm.py                   # Model routing, schema, fallback, budgets
│   ├── models.py                # Validated request and state contracts
│   ├── orchestrator.py          # Agent collaboration workflow
│   ├── policy.py                # Ethical and legal guardrails
│   ├── runtime.py               # Dependency bootstrap and campaign seed
│   ├── scheduler.py             # Durable heartbeat
│   └── store.py                 # SQLite schema and persistence
├── config/campaign.yaml         # WegMetDieKilos campaign profile
├── docs/
│   ├── ARCHITECTURE.md          # Source-to-derivative feature mapping
│   ├── IMPLEMENTATION_PLAN.md   # Step-by-step adaptation plan
│   └── RAILWAY.md               # Deployment guide
├── scripts/start.sh             # Container/Railway start script
├── skill/paypro-campaign-automaton/
│   ├── SKILL.md                 # Installable reusable skill
│   ├── references/api_reference.md
│   └── templates/campaign.yaml
├── tests/                       # Core and API tests
├── .env.example                 # Safe configuration template
├── Dockerfile
├── docker-compose.yml
├── app.py                       # ASGI shim
├── main.py                      # Local CLI shim
└── pyproject.toml
```

## Quickstart

Python 3.11 or newer is required. The commands below create an isolated environment, install the application, initialize the database, and run the full workflow without spending model credits.

```bash
git clone https://github.com/mmgblabel-png/autotrader.git automaton-paypro-kilos
cd automaton-paypro-kilos

python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env before continuing.
set -a; . ./.env; set +a

# Use deterministic mode for the first validation run.
export LLM_PROVIDER=deterministic
python -m campaign_automaton init
python -m campaign_automaton run \
  --campaign wegmetdiekilos-bronze \
  --workflow full_campaign \
  --force
python -m campaign_automaton artifacts \
  --campaign wegmetdiekilos-bronze
```

Start the API and heartbeat:

```bash
python -m campaign_automaton serve --port 8000
```

Open `http://localhost:8000/docs` for the interactive API documentation. Check health without a token:

```bash
curl http://localhost:8000/api/health
```

## PayPro configuration

Copy `.env.example` to `.env`. Never commit `.env`, database files, secrets, or exports.

```dotenv
PAYPRO_PRODUCT_URL=https://www.paypro.nl/producten/WegMetDieKilos_Bronze_Plan/114766/183297
PAYPRO_AFFILIATE_ID=VUL_HIER_JOUW_EIGEN_ID_IN
PAYPRO_AFFILIATE_URL_TEMPLATE={product_url}
PUBLIC_BASE_URL=http://localhost:8000
CONTROL_TOKEN=CHANGE_ME
WEBHOOK_TOKEN=CHANGE_ME_TOO
```

`PAYPRO_PRODUCT_URL` may already be the exact affiliate destination supplied by your account. PayPro URL formats can be account- and campaign-specific, so the application never guesses an affiliate query parameter. Paste the exact format shown in your PayPro account into `PAYPRO_AFFILIATE_URL_TEMPLATE`; it may contain `{product_url}` and/or `{affiliate_id}`.

| Example template | Behavior |
|---|---|
| `{product_url}` | Preserve the exact supplied URL and add only UTM attribution |
| `https://affiliate.example/ref/{affiliate_id}` | Substitute the configured affiliate ID |
| `https://affiliate.example/?id={affiliate_id}&target={product_url}` | Substitute both values |

The internal campaign link has this shape:

```text
https://<your-domain>/r/wegmetdiekilos-bronze?src=blog&content=<artifact-id>
```

A request to that URL records a pseudonymous click and returns HTTP 302 to the resolved PayPro destination with `utm_source`, `utm_medium`, `utm_campaign`, and `utm_content`. Validate the final destination before publishing any link.

## Secure local configuration

Generate separate random secrets. CORS is not authentication; the owner token remains required on control endpoints.

```bash
openssl rand -hex 32   # CONTROL_TOKEN
openssl rand -hex 32   # WEBHOOK_TOKEN
```

| Variable | Recommended first-run value | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `deterministic` | No-cost validation mode |
| `DRAFT_ONLY` | `true` | Blocks outbound actions |
| `AUTO_RUN_DUE_CAMPAIGNS` | `false` | Prevents unattended model runs during setup |
| `HEARTBEAT_ENABLED` | `true` | Enables recovery and scheduler status |
| `DATA_DIR` | `./data` | Local persistent state |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Internal tracking links |

After validating deterministic mode, set `OPENAI_API_KEY` and `LLM_PROVIDER=auto` to enable model-generated structured outputs. The default live model is `gpt-5-mini`, with `gpt-5-nano` as a configured fallback. Per-run, hourly, and daily request caps prevent runaway usage.

## Start a campaign

The default campaign is seeded from `config/campaign.yaml`. It starts in `draft` state. A manual run works in any state; scheduled execution considers only `active` campaigns.

```bash
python -m campaign_automaton set-status \
  --campaign wegmetdiekilos-bronze \
  --status active

python -m campaign_automaton run \
  --campaign wegmetdiekilos-bronze \
  --workflow full_campaign \
  --force
```

Run a narrower workflow or selected channels:

```bash
python -m campaign_automaton run \
  --campaign wegmetdiekilos-bronze \
  --workflow content \
  --channels blog email social \
  --force

python -m campaign_automaton run \
  --campaign wegmetdiekilos-bronze \
  --workflow analytics \
  --force
```

| Workflow | Agents |
|---|---|
| `full_campaign` | Research → SEO → Marketing → Analytics |
| `research` | Research only |
| `seo` | Research → SEO |
| `content` | Research → SEO → Marketing |
| `analytics` | Analytics only |

Non-forced runs are idempotent by campaign, workflow, channel set, and UTC date. Use `--force` only when a genuinely new version is intended.

## Review and approve content

Every generated artifact starts as `draft`. A blocked artifact remains visible for diagnosis but cannot be approved.

```bash
python -m campaign_automaton artifacts \
  --campaign wegmetdiekilos-bronze

python -m campaign_automaton review <artifact-id> \
  --decision approved \
  --reviewer owner \
  --notes "Claims, source gaps, disclosure, destination, and channel rules checked"

# Execute exactly one lease-protected scheduler tick.
python -m campaign_automaton heartbeat-once

# Inspect content and outbound-action policy gates.
python -m campaign_automaton policy-check \
  --channel social \
  --content "Gegarandeerd 10 kilo in 2 weken zonder moeite!" \
  --no-add-disclosure
python -m campaign_automaton action-check \
  --action publish \
  --human-confirmed
```

Before approval, verify product facts, destination URL, affiliate attribution, disclosure placement, spelling, channel rules, consent requirements, and whether medical context needs professional-advice language.

## API examples

Owner endpoints require `X-Control-Token`.

```bash
export BASE=http://localhost:8000
export CONTROL_TOKEN='your-secret'

curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/campaigns"

curl -X POST \
  "$BASE/api/campaigns/wegmetdiekilos-bronze/runs" \
  -H "Content-Type: application/json" \
  -H "X-Control-Token: $CONTROL_TOKEN" \
  -H "Idempotency-Key: weekly-content-2026-35" \
  -d '{"workflow":"content","channels":["blog","email","social"],"force":false}'

curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/campaigns/wegmetdiekilos-bronze/artifacts"
```

The webhook uses a separate token and idempotent external event ID:

```bash
curl -X POST "$BASE/api/webhooks/events" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: $WEBHOOK_TOKEN" \
  -d '{
    "provider":"custom",
    "event":{
      "campaign_slug":"wegmetdiekilos-bronze",
      "event_type":"conversion",
      "source":"blog",
      "medium":"affiliate",
      "content_id":"artifact-id",
      "event_id":"provider-unique-id",
      "value":0,
      "metadata":{}
    }
  }'
```

Do not include names, email addresses, health data, full IP addresses, or other direct identifiers in event metadata.

## Analytics and optimization

The analytics endpoint returns total views, clicks, signups, conversions, attributed value, click-through rate, conversion rate, and source breakdown.

```bash
curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/campaigns/wegmetdiekilos-bronze/analytics"
```

`AnalyticsAgent` records uncertainty and proposes one reversible test. It never changes production content automatically. Use sufficient data, change one principal variable per test, choose a measurement window in advance, and preserve the existing version as a control.

Review optimization proposals explicitly:

```bash
curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/campaigns/wegmetdiekilos-bronze/optimizations"

curl -X POST "$BASE/api/optimizations/<proposal-id>/decision" \
  -H "Content-Type: application/json" \
  -H "X-Control-Token: $CONTROL_TOKEN" \
  -d '{"decision":"accepted","reviewer":"owner","notes":"Run as a controlled experiment"}'
```

Accepting a proposal records the decision; it does not publish or change content automatically.

## Scheduler behavior

The heartbeat uses a database lease to avoid overlapping work. Each tick recovers stale runs, executes queued work, optionally runs due active campaigns, calculates the next cron occurrence, and records history. Keep `AUTO_RUN_DUE_CAMPAIGNS=false` until the full manual quality gate is complete.

| Setting | Default | Meaning |
|---|---:|---|
| `HEARTBEAT_ENABLED` | `true` | Start background heartbeat with the API |
| `HEARTBEAT_INTERVAL_SECONDS` | `30` | Minimum tick delay |
| `AUTO_RUN_DUE_CAMPAIGNS` | `false` | Do not spend model requests automatically during setup |
| Campaign `schedule_cron` | `0 9 * * 1` | Weekly Monday schedule when auto-run is enabled |

Run only one SQLite-backed service instance. If the system later migrates to PostgreSQL with a proper queue, the API and workers may be separated safely.

## Railway deployment

Railway detects and builds a root `Dockerfile` automatically.[4] It injects `PORT`, which the start script passes to Uvicorn, and it activates the deployment after `/api/health` returns HTTP 200.[5] Ordinary deployment storage is ephemeral, so the included project configuration creates a volume mounted at `/data`.[3] [6]

Railway’s older `railway.json` and `railway.toml` configuration format is deprecated and has a hard cutoff on 2026-12-01. This repository uses the replacement `.railway/railway.ts` project-level format.[7]

```bash
railway login
railway link
railway config plan
railway config apply
```

Configure these secrets in Railway before deployment:

| Variable | Required | Notes |
|---|---:|---|
| `PUBLIC_BASE_URL` | Yes | Final Railway HTTPS domain; update after the domain is assigned |
| `CONTROL_TOKEN` | Yes | Long random owner token |
| `WEBHOOK_TOKEN` | Yes | Different long random callback token |
| `PAYPRO_AFFILIATE_ID` | Account-dependent | Your own PayPro ID |
| `PAYPRO_AFFILIATE_URL_TEMPLATE` | Account-dependent | Exact account-provided format |
| `OPENAI_API_KEY` | Optional | Omit for deterministic mode |
| `OPENAI_BASE_URL` | Optional | OpenAI-compatible endpoint |

The Railway service uses one replica and one 512 MB volume. Railway documents that a volume can attach to only one service, cannot be used with replicas, and causes a small amount of redeployment downtime to protect data integrity.[3]

After deployment:

```bash
curl https://<your-domain>/api/health
curl -H "X-Control-Token: $CONTROL_TOKEN" \
  https://<your-domain>/api/config/status
```

Confirm that `affiliate.ready` is true, `database_ok` is true, `draft_only` is true, and the tracking redirect resolves to the correct PayPro destination before sharing any link.

## Docker deployment

Run the same topology locally:

```bash
cp .env.example .env
# Edit .env first.
docker compose up --build -d
docker compose ps
curl http://localhost:8000/api/health
```

The named Docker volume persists `/data`. Use `docker compose down` to stop the service without deleting its volume. Do not use `docker compose down -v` unless permanent data deletion is intentional.

## Reusable Manus skill

The installable skill lives at:

```text
skill/paypro-campaign-automaton/SKILL.md
```

It defines the required inputs, agent contracts, workflow, API, campaign cloning rules, model budgets, approval gates, ethical constraints, and Railway deployment procedure. The same package also contains a generic campaign template and detailed API reference.

## Create or clone a campaign

Create campaigns through the API or copy `skill/paypro-campaign-automaton/templates/campaign.yaml`, give it a new slug, and validate every product fact. Do not copy tracking events, approvals, secrets, or personal data from another campaign.

```bash
curl -X POST "$BASE/api/campaigns" \
  -H "Content-Type: application/json" \
  -H "X-Control-Token: $CONTROL_TOKEN" \
  -d '{
    "name":"New Product Campaign",
    "slug":"new-product-campaign",
    "product_name":"New Product",
    "product_url":"https://example.com/exact-affiliate-url",
    "audience":"A precise opt-in audience description of at least ten characters.",
    "market":"Nederland",
    "language":"nl-NL",
    "channels":["blog","email","social"],
    "goals":["Create value-first opt-in demand"],
    "product_facts":["Only include verified facts"],
    "prohibited_claims":["No guarantees"],
    "schedule_cron":"0 9 * * 1",
    "metadata":{}
  }'
```

For a closely related offer, clone only safe configuration and reset product facts by default:

```bash
curl -X POST "$BASE/api/campaigns/wegmetdiekilos-bronze/clone" \
  -H "Content-Type: application/json" \
  -H "X-Control-Token: $CONTROL_TOKEN" \
  -d '{
    "name":"New Plan Campaign",
    "slug":"new-plan-campaign",
    "product_name":"New Plan",
    "product_url":"https://example.com/exact-affiliate-url",
    "reset_product_facts":true
  }'
```

The clone starts in `draft` and receives no runs, events, approvals, or secrets from the source campaign.

## Ethical and legal guardrails

The policy engine blocks guaranteed, rapid, effortless, medical, and unsupported numerical weight-loss claims. It also blocks bought lists, profile scraping, unsolicited email or DMs, sensitive-data collection, fake testimonials, and manipulative spam patterns. Sales content receives an affiliate disclosure automatically.

| Allowed | Not allowed |
|---|---|
| Helpful public content | Duplicate spam across communities |
| Opt-in email drafts with unsubscribe reminder | Unsolicited email or direct messages |
| Public-source topic research without profile collection | Scraping people or buying contact lists |
| Realistic “may help” language | Guaranteed results or exact kilo/time promises |
| Transparent affiliate disclosure | Hidden commercial relationship |
| Human-reviewed community replies where rules allow | Rule evasion or covert promotion |
| Pseudonymous click and conversion events | Health profiles or direct identifiers in analytics |

This software is a workflow and drafting tool, not medical, legal, or privacy advice. The operator remains responsible for the final claims, consent basis, platform compliance, disclosures, data processing, and product terms.

## Testing and quality checks

```bash
pytest
ruff check campaign_automaton tests
python /home/ubuntu/skills/skill-creator/scripts/quick_validate.py \
  /home/ubuntu/skills/paypro-campaign-automaton
```

The 18-test suite covers default campaign seeding, full four-agent runs, deterministic fallback, disclosure insertion, unsupported-claim blocking, action blocking, affiliate template substitution, run idempotency, atomic heartbeat execution, event deduplication, direct-identifier rejection, analytics aggregation, campaign cloning, optimization decisions, API authentication, artifact approval, webhook ingestion, and tracked redirects.

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| `503 Control API is disabled` | `CONTROL_TOKEN` is missing | Set a long server-side token and restart |
| `401 Invalid token` | Wrong header or token | Send `X-Control-Token` or `X-Webhook-Token` exactly |
| Tracking link uses localhost | `PUBLIC_BASE_URL` not updated | Set the final Railway HTTPS domain and redeploy |
| Affiliate ID is not present | Template uses only `{product_url}` | Paste the exact account-provided affiliate template |
| Run says deterministic | No model key or deterministic provider | Configure `OPENAI_API_KEY` and `LLM_PROVIDER=auto` |
| Artifact cannot be approved | Blocking policy finding | Correct the claim or acquisition method and generate a new version |
| Database resets after deploy | No Railway volume or wrong `DATA_DIR` | Mount `/data` and set `DATABASE_PATH=/data/campaign_automaton.db` |
| Scheduler does not run campaigns | Auto-run is intentionally disabled | Complete quality checks, activate campaign, then enable it |
| Duplicate webhook counts | Provider omitted stable `event_id` | Send one unique external event ID per event |

## License and attribution

The original Conway Automaton repository is MIT-licensed, permitting use, modification, and distribution with preservation of the copyright and license notice.[8] This derivative contains its own campaign-specific implementation and includes the MIT license and source attribution.

## References

[1]: https://github.com/Conway-Research/automaton "Conway Research — Automaton"
[2]: https://www.paypro.nl/producten/WegMetDieKilos_Bronze_Plan/114766/183297 "PayPro product URL supplied for WegMetDieKilos Bronze Plan"
[3]: https://docs.railway.com/volumes/reference "Railway Docs — Volumes"
[4]: https://docs.railway.com/builds/dockerfiles "Railway Docs — Dockerfiles"
[5]: https://docs.railway.com/deployments/healthchecks "Railway Docs — Healthchecks"
[6]: https://docs.railway.com/deployments/reference "Railway Docs — Deployments reference"
[7]: https://docs.railway.com/infrastructure-as-code "Railway Docs — Infrastructure as Code"
[8]: https://github.com/Conway-Research/automaton/blob/main/LICENSE "Conway Automaton MIT License"


## Self-hosted campaign website

The application can host its own campaign website at `/site/<campaign-slug>` without requiring WordPress or a social-media account. It renders **only the latest owner-approved artifacts that have passed policy review**. Draft, rejected, blocked, and unreviewed artifacts remain inaccessible. Calls to action use the first-party `/r/<campaign-slug>` tracker before the visitor is redirected to the verified PayPro destination.

The website is private by default. Set `WEBSITE_ENABLED=true` only after reviewing the landing-page and blog artifacts and deciding that they may be visible publicly. The protected status endpoint provides the enabled state and publishable artifact types:

```bash
curl -H "X-Control-Token: $CONTROL_TOKEN" \
  "$BASE/api/publisher/status"
```

Set `WEBSITE_ENABLED=false` to hide the public routes immediately; campaign records and approved artifacts are retained in SQLite for later review. Public visibility is distinct from scheduled draft generation and must be approved explicitly by the owner.
