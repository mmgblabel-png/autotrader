# Multi-Product Affiliate Portfolio Architecture

## Purpose

Extend the existing self-hosted campaign site from a single approved campaign into a small, transparent affiliate portfolio. The system must keep attribution, artifacts, policy results, approvals, analytics, and optimization proposals separate for every product. It must never add a product, enroll in a campaign, or publish a new product page simply because its commission appears high.

## Product-selection decision

The current research does **not** justify adding five additional campaigns automatically. The available portfolio contains several products with strong medical, disease, or guaranteed-weight-loss claims that conflict with the live site’s policy. The launch portfolio should therefore use a staged, evidence-led approach.

| Rank | Product | Role | Decision prerequisite |
|---:|---|---|---|
| 1 | WegMetDieKilos Bronze Plan | Existing weight-management quiz campaign | Already active and independently verified |
| 2 | Practice Happy with Yoga | Low-intensity movement and wellbeing category | Verify the active affiliate enrollment and exact account-issued destination; select one subscription term only |
| 3 | Online Cursus Fermenteren | Educational food-skills category | Verify active affiliate enrollment and exact destination; use food-safety and cooking framing only |
| 4 | Mijn Keto Menu | Conditional dietary-planning category | Require heightened health-policy review, medical-disclaimer placement, no outcome claims, and exact destination verification |
| 5 | Reserve slot | Do not fill with Afslank Receptenbijbel, Keto Brons Plan, or Sunsbest | These pages currently present claims outside the project’s responsible-claims boundary |

This approach prioritizes audience fit, policy compatibility, clarity of offer, support/terms, and measured engagement over headline commission or platform score.

## Data and attribution model

Each product becomes its own existing `campaigns` record. Its `slug`, `product_url`, product facts, claims policy, schedule, content artifacts, views, clicks, conversions, audit records, and optimization proposals are already independently scoped in the SQLite model.

The link model remains product-specific:

```text
Public page -> /r/<campaign-slug>?src=<source>&content=<artifact>
            -> event record scoped to campaign slug
            -> exact verified PayPro product URL + UTM values
```

`PAYPRO_AFFILIATE_URL_TEMPLATE={product_url}` remains correct only when every campaign's `product_url` is an exact owner-issued PayPro affiliate destination. No guessed affiliate parameter is permitted.

## Public-site model

The existing publisher will retain campaign-specific URLs such as `/site/wegmetdiekilos-bronze`. The multi-product extension adds a portfolio index that lists only product pages whose campaign status is active, whose website visibility is enabled, and whose page has a policy-cleared owner-approved landing artifact. It will never expose draft or blocked products.

The user-facing product page always contains an affiliate disclosure, a responsible-lifestyle context, a tracked CTA, and a link to terms/privacy where available. It must not reproduce claims, guarantees, testimonials, or medical assertions from a merchant page.

## Continuous operation and improvement

Railway’s existing 30-second heartbeat maintains durable leases, recovery, and scheduled execution. Each active campaign is evaluated at its own cron time. The full campaign workflow records fresh content drafts and an analytics report; publication remains approval-gated.

The optimization loop must follow these rules:

1. Treat no sales without enough tracked views and clicks as an **insufficient-evidence** signal, not proof that content or a product failed.
2. Check event integrity and PayPro conversion callbacks before changing a CTA, offer framing, or product mix.
3. Propose one reversible, measurable change at a time with a defined measurement window and stop condition.
4. Keep the current published version as a control.
5. Require explicit owner approval for changed public artifacts and for activation of any new campaign.
6. Never use cold outreach, personal-data targeting, unverifiable health claims, or deceptive urgency.

## Release gates

| Gate | Required evidence | Action |
|---|---|---|
| Affiliate eligibility | The owner can view the product as active/promotable in PayPro and supplies or verifies the exact account-issued destination | Create a draft campaign only |
| Content policy | Every draft has `policy.allowed=true`, disclosure, and product-fact review | Make it reviewable |
| Owner review | Explicit artifact approval and explicit approval to expose the new product | Enable its public page |
| Measurement | First-party views/clicks and a valid conversion callback or export | Permit analytics proposal generation |
| Optimization | One-variable experiment, adequate measurement window, no policy issue | Require separate owner decision before publication |

## 24/7 operating boundary

The service may stay online continuously for scheduling, monitoring, recovery, content-draft generation, tracking, and evidence-based optimization proposals. It may not autonomously enroll in third-party campaigns, publish newly generated product content, contact potential customers, or change an affiliate destination without owner approval.
