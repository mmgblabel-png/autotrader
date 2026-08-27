# Nine-Agent Campaign Operating Model

## Scope and authority

The current runtime contains four specialist agents: **Research**, **SEO**, **Marketing**, and **Analytics**. The requested expansion adds five more—**Compliance**, **Editorial Quality**, **Distribution**, **Attribution Integrity**, and **Operations Reliability**—for a total of **nine operating agents**. The policy engine, scheduler, and approval gate are system controls, not agents.

Every output remains a private artifact until an owner reviews it. No agent may accept PayPro terms, create an external account, publish a page, send an email, post on social media, join a group, purchase ads, change an affiliate destination, or modify a production setting.

| Agent | Purpose | Permitted output | Explicitly prohibited |
|---|---|---|---|
| Research | Bound product and audience research | Source gaps, angle hypotheses, research brief | Inventing product facts or contacting people |
| Compliance | Merchant-term and claim preflight | Checklists, warnings, review questions | Overriding the policy engine or approving publication |
| SEO | Search-intent and on-site information architecture | Keyword themes, metadata, internal-link ideas | Ranking guarantees or scraped competitor content |
| Editorial Quality | Clear, factual Dutch-language review | Revision brief, readability and disclosure review | Inventing customer stories or endorsements |
| Marketing | Product-specific landing, article, email, and social drafts | Draft campaign copy with affiliate disclosure | Unsubstantiated claims, urgency tricks, direct outreach |
| Distribution | Ethical, free owned-and-earned distribution plan | UTM creative plan, owned-site and opt-in channel checklist | Auto-posting, group spam, purchased reach, cold messages |
| Attribution Integrity | UTM and callback measurement hygiene | Source taxonomy, tracking audit, anomaly flags | Visitor-level profiling or raw callback exposure |
| Analytics | Evidence-based measurement interpretation | Confidence-tagged observation, reversible test proposal | Declaring causality from low-volume data |
| Operations Reliability | Scheduler, budget, and data-freshness assurance | Run-health summary, pause/escalation recommendation | Self-modification, secret rotation, or autonomous activation |

## Workflow design

The primary `full_campaign` workflow will execute in this order: Research, Compliance, SEO, Editorial Quality, Marketing, Distribution, Attribution Integrity, Analytics, and Operations Reliability. The sequence passes concise, structured upstream summaries only. Each agent has one responsibility and cannot execute side effects.

The lean workflows remain bounded: `content` excludes Analytics and Operations; `analytics` uses Attribution Integrity, Analytics, and Operations Reliability; and `research` runs Research followed by Compliance. This keeps scheduled activity meaningful rather than multiplying similar artifacts.

## Ethical free-distribution playbook

The Distribution Agent produces no automatic advertisements. Its permitted free strategy is a measured owned-media plan: maintain an approved article and FAQ on the owner-controlled website; create one named, factual creative variant per channel; use UTM tags that identify source, medium, campaign, and content; and queue optional social or email drafts for manual owner review.

It may suggest participation in communities only where the owner has an established, permitted account and the channel rules allow relevant, disclosed links. It must recommend value-first discussion rather than copied link drops. It may not recommend posting in unmanaged Facebook groups, buying followers, cold DMs, automated comments, misleading comparison pages, false scarcity, or hidden affiliate links. Merchant-specific terms always override the playbook.

## Improvement strategy

The system uses a three-stage evidence ladder. First, **data integrity** confirms that inbound UTM values, first-party redirect clicks, and signed PayPro conversions are attributable. Second, **signal formation** starts only when a campaign has at least 100 views and 20 clicks; until then, the system may recommend measurement repairs but not conversion conclusions. Third, **reversible learning** permits one owner-approved change at a time, such as a factual headline angle, CTA placement, or internal-link placement. It compares the change using the same UTM taxonomy and does not alter product facts, disclosures, prices, or risk language.

A 24-hour window is a freshness and operations check, not a sales ultimatum. A lack of sales in 24 hours is labelled insufficient evidence unless traffic and click thresholds have been met. The Operations Reliability Agent recommends a pause or human review when callback signatures fail, tracking data is stale, a policy rejection recurs, a merchant restriction is ambiguous, or the configured model budget is exceeded.

## Product selection criteria

The six private candidates were selected for clear, fact-bounded course or owned-site products: Freds Bouwtekeningen, Communicatie Canvas Micro Learnings, PromptSchool.online AI course, Mindfulness voor het Dagelijkse leven, Yoga Stap voor Stap, and Yoga Nidra. They will remain private until the owner accepts the specific PayPro terms, if presented, and approves each campaign's factual draft assets.
