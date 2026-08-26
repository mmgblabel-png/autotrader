# Implementation Plan

**Author:** Manus AI  
**Project:** WegMetDieKilos PayPro Campaign Automaton

## 1. Objective

Transform the selected `mmgblabel-png/autotrader` repository into a complete, Railway-deployable affiliate campaign runtime based on the useful architectural patterns in `Conway-Research/automaton`. The result must generate valuable drafts, measure pseudonymous events, propose optimizations, and retain human approval while avoiding spam, deceptive claims, autonomous publishing, wallets, payments, and unbounded self-modification.[1]

## 2. Local structure

```text
~/Downloads/paypromoney/
├── automaton-paypro-kilos/      # Adapted Git repository
└── automaton-reference/         # Read-only Conway reference clone
```

The working repository may still have the GitHub remote name `autotrader`; the recommended local folder name is `automaton-paypro-kilos` so its new purpose is immediately clear.

## 3. Adaptation sequence

| Step | Action | Result |
|---:|---|---|
| 1 | Clone `mmgblabel-png/autotrader` and `Conway-Research/automaton` | Editable target plus read-only reference |
| 2 | Inventory the reference loop, heartbeat, state, memory, skills, policies, model routing, observability, self-modification, and replication | Feature map and exclusions |
| 3 | Retain Python/FastAPI as the portable target stack | Existing Railway-friendly service pattern remains useful |
| 4 | Remove trading, exchange, blockchain, wallet, and PnL modules | One coherent campaign product |
| 5 | Add campaign configuration, validated models, and SQLite schema | Durable campaign state |
| 6 | Implement Research, SEO, Marketing, and Analytics agents | Required role separation and collaboration |
| 7 | Implement the orchestrator and heartbeat | Continuous, idempotent, recoverable runs |
| 8 | Implement policies and affiliate-link builder | Disclosure, claims, privacy, consent, and link consistency |
| 9 | Implement control API, webhook, redirect, CLI, and audit endpoints | Integration with Manus, websites, and analytics tools |
| 10 | Add Docker, current Railway IaC, volume, health check, and startup scripts | Deployable service with persistent state |
| 11 | Create and validate a reusable Manus skill | Repeatable setup for future products |
| 12 | Run tests, linter, deterministic smoke run, Docker build, and secret scan | Release quality gate |

## 4. Files added or replaced

| Path | Change |
|---|---|
| `campaign_automaton/agents/` | Four specialized agents and shared structured contract |
| `campaign_automaton/api.py` | FastAPI control plane, webhook, analytics, and redirect |
| `campaign_automaton/config.py` | Environment settings and production validation |
| `campaign_automaton/links.py` | Affiliate destination and UTM/tracking URLs |
| `campaign_automaton/llm.py` | Structured model client, budgets, fallback, and usage records |
| `campaign_automaton/models.py` | Pydantic request/state contracts |
| `campaign_automaton/orchestrator.py` | Ordered campaign workflow and artifacts |
| `campaign_automaton/policy.py` | Claims, spam, consent, privacy, disclosure, and approval rules |
| `campaign_automaton/runtime.py` | Database and dependency bootstrap |
| `campaign_automaton/scheduler.py` | Lease-protected heartbeat and scheduled runs |
| `campaign_automaton/store.py` | SQLite schema, CRUD, memory, events, audit, usage, and leases |
| `config/campaign.yaml` | WegMetDieKilos Bronze Plan campaign seed |
| `.env.example` | PayPro, security, model, scheduler, and persistence variables |
| `Dockerfile` | Production container |
| `scripts/start.sh` | Database initialization and Uvicorn startup |
| `.railway/railway.ts` | Current Railway project-level service and volume definition |
| `docker-compose.yml` | Matching local container topology |
| `skill/paypro-campaign-automaton/` | Installable skill, API reference, and campaign template |
| `tests/` | Core and API acceptance coverage |
| `README.md` | Complete installation and operations guide |
| `docs/ARCHITECTURE.md` | Source-feature mapping and security model |
| `docs/RAILWAY.md` | Production deployment procedure |

The old trading package, trading configuration, blockchain policy notes, and deprecated `railway.json` are removed. Railway’s documentation identifies `.railway/railway.ts` as the replacement for the deprecated service-level configuration format.[2]

## 5. Rollout stages

### Stage A — deterministic local validation

Run without an API key, inspect all artifacts, test the tracked redirect, insert a test conversion event, and verify analytics. Keep the campaign in `draft`, `DRAFT_ONLY=true`, and `AUTO_RUN_DUE_CAMPAIGNS=false`.

### Stage B — model-assisted drafts

Configure the model key, run one forced campaign, compare structured outputs with deterministic versions, verify source gaps, and review every policy result. Maintain strict request budgets.

### Stage C — Railway staging

Apply the service and volume, set the final HTTPS base URL and secrets, confirm `/api/health`, test the redirect, verify persistence across one redeploy, and keep scheduled generation disabled.

### Stage D — controlled production

Activate the campaign, approve representative artifact types, enable scheduled due runs only when model spending and review capacity are understood, and connect conversion data only through an authenticated, documented callback or controlled import.

## 6. Acceptance criteria

| Area | Acceptance criterion |
|---|---|
| Installation | Clean Python environment installs from `pyproject.toml` |
| Campaign | Default WegMetDieKilos campaign is seeded once and can be cloned safely |
| Agents | All four agents execute in the intended order and preserve upstream results |
| Policy | Unsupported claims and unsolicited acquisition methods are blocked |
| Disclosure | Sales-oriented artifacts contain an affiliate disclosure |
| Tracking | Redirect records one click and retains the correct PayPro destination |
| Webhook | Stable external event IDs deduplicate callbacks |
| Analytics | Views, clicks, signups, conversions, rates, and source breakdown are correct |
| Approval | Drafts require human approval; blocked drafts cannot be approved |
| Persistence | Railway volume stores SQLite under `/data` |
| Health | `/api/health` reports database and heartbeat readiness |
| Security | No secrets, `.env`, or databases are committed |
| Quality | Tests, lint, skill validation, deterministic smoke run, and container build pass |

## 7. References

[1]: https://github.com/Conway-Research/automaton "Conway Research — Automaton"
[2]: https://docs.railway.com/infrastructure-as-code "Railway Docs — Infrastructure as Code"
