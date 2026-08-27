# Deployment Session Notes

**Date:** 2026-08-26

## Railway access inspection

The command-line client is installed at version 5.44.1 but is not authenticated in the sandbox. The connected browser is authenticated to Railway under **Lumar Richardson's Projects** on the Hobby plan. One existing project named **loving-art** is visible and currently reports **No services**.

No resources, settings, services, variables, volumes, deployments, domains, or payments were changed during this inspection.

## Pending decision

Deployment can target the existing empty `loving-art` project or a new Railway project. Creating or configuring a service and volume may have billing or resource implications and requires explicit confirmation immediately before applying the changes.

## Railway deployment attempt

A dedicated Railway project was created (initially auto-named `spirited-success`) with project ID `16a977c9-7d11-4960-9603-cd10049366ab`, environment `production`, service `web`, and the generated public domain `https://web-production-61a287.up.railway.app`.

The service source branch was changed to `feat/paypro-campaign-automaton`. A persistent volume named `web-volume` was created and attached at `/data`. Production variables were staged and deployed, including HTTPS public base URL, `/data/campaign_automaton.db`, deterministic LLM mode, draft-only operation, disabled automatic due-campaign execution, heartbeat enabled, and separate high-entropy control and webhook tokens.

### Startup diagnosis

The public `GET /api/health` request returned Railway `502 Bad Gateway`. Railway deploy logs show the default service command passed the literal string `$PORT` to Uvicorn:

> `Error: Invalid value for '--port': '$PORT' is not a valid integer.`

The service settings show Dockerfile detection is active, but the deployment must be corrected by configuring the tested shell startup script (`./scripts/start.sh`), which expands the Railway-assigned port, and setting the health check to `/api/health`.

No campaign content was published, no outbound messages were sent, `DRAFT_ONLY=true` is retained, and `AUTO_RUN_DUE_CAMPAIGNS=false` is retained.

## Successful recovery and live verification

The initial Railway deployment exposed two platform-specific issues: Railway's default command did not expand a literal `$PORT`, and the newly mounted Railway volume was root-owned. The service configuration was corrected to use `./scripts/start.sh` with `/api/health` as its health check. Commit `f38ea3a` updated the image/startup sequence to make only the mounted data directory writable and then re-execute as the constrained `app` account.

Railway deployment logs confirmed the recovered service started on its assigned port, completed the FastAPI lifecycle, and answered the platform probe with `GET /api/health` returning `200 OK`. The public production endpoint is:

`https://web-production-61a287.up.railway.app`

### Live endpoint verification

All live checks were executed in deterministic, draft-only mode with automatic due-campaign execution disabled. The public root and health endpoints returned HTTP 200. Health confirmed `environment=production`, `database_ok=true`, heartbeat running at a 30-second interval with no errors, `draft_only=true`, and deterministic LLM mode.

The protected control API rejected a request without a token with HTTP 401 and returned HTTP 200 when authenticated. Its runtime status confirmed `/data` persistence, draft-only behavior, deterministic AI mode, and `AUTO_RUN_DUE_CAMPAIGNS=false`. The seeded `wegmetdiekilos-bronze` campaign is present as a `draft` with no next run scheduled.

A test request to `/r/wegmetdiekilos-bronze` returned HTTP 302 to the configured PayPro destination with first-party UTM values. A deliberately unauthenticated webhook returned HTTP 401. A single clearly labeled pseudonymous verification webhook was accepted once (`created=true`); an identical replay was accepted idempotently with `created=false` and the same event ID. Audit entries were written for both deliveries. The test created exactly one `view` and one `click` event, both sourced `railway-live-verification`, and no conversion, signup, personal identifier, health data, campaign run, content artifact, outbound message, or publication.

The direct PayPro URL currently remains the configured destination. Because PayPro parameter formats are account-specific, an operator should set `PAYPRO_AFFILIATE_URL_TEMPLATE` to the exact PayPro affiliate URL format supplied by their account before treating any clicks as commission-attributed.

## Local CLI scheduler and approval-gate verification

The local CLI verification used isolated SQLite state and deterministic AI mode. The first `heartbeat-once` command recovered no stale runs and executed exactly one queued workflow (`394ef31f-fae1-4a9e-8dd2-73cc27e39261`); an immediate second heartbeat executed no workflow, demonstrating the due-run claim was not repeated.

A policy inspection of `Gegarandeerd 10 kilo in 2 weken zonder moeite!` was blocked for an unsupported weight-loss guarantee and for a missing affiliate disclosure. The local review path approved a policy-allowed social draft only after its content, disclosure, destination, and channel were reviewed. Its policy record remained `allowed=true` with the disclosure added. A separate stored artifact with blocking policy findings was rejected by the CLI review gate. These local validations generated no external publication, email, message, lead scraping, or paid action.


## 2026-08-26 — Self-hosted website publication

The self-hosted publisher was deployed from `d872ce6` with `WEBSITE_ENABLED` initially disabled. Local visual verification and the automated suite confirmed that public rendering is limited to artifacts with both `status=approved` and `policy.allowed=true`.

After explicit owner confirmation, production settings were changed to `DRAFT_ONLY=false`, `AUTO_RUN_DUE_CAMPAIGNS=true`, `SCHEDULE_TIMEZONE=Europe/Amsterdam`, and `WEBSITE_ENABLED=true`. The WegMetDieKilos campaign was activated with cron `0 0 * * *`. The durable next run is `2026-08-26T22:00:00+00:00`, which is `2026-08-27 00:00 CEST` in Europe/Amsterdam.

The deterministic initial website workflow generated four artifacts. Two website artifacts passed policy review and were approved under the `owner-authorized-publish` reviewer identity: `925815e1-70ec-4363-b9fb-143a532c762c` (`landing_page_copy`) and `c7ebd584-c341-487e-8a44-2d68e8545024` (`blog_article`). Both include the affiliate disclosure and medical-context caution. The website is publicly available at `/site/wegmetdiekilos-bronze`.

Live verification returned health `ok`, publisher status `enabled=true` with two approved publishable artifact types, and HTTP 302 from the first-party tracking route to the verified PayPro URL with `utm_source=website-live-verification`, `utm_medium=affiliate`, `utm_campaign=wegmetdiekilos-bronze`, and `utm_content=hero-cta`. The public page was also visually inspected and correctly displayed the hero, conservative claims, disclosure, approved landing content, and article link.


## Conservative multi-product portfolio publication — 2026-08-26/27 CEST

The owner explicitly authorized publication of the conservative portfolio after private policy review. The following campaigns are now active and publicly represented in the self-hosted portfolio:

| Campaign | PayPro destination verified from authenticated detail | Public-page approval | Next scheduled run |
|---|---|---|---|
| `practice-happy-yoga` | `https://www.paypro.nl/producten/Maandabonnement_-_Practice_Happy_with_Yoga/57261/183297` | Approved landing artifact `e0a5eeb1-ce81-4510-9845-a81f75afa316` and blog artifact `2342b063-4d86-4243-952c-fff8f579c1c0` | 2026-08-27T22:00:00+00:00 (00:00 Europe/Amsterdam) |
| `online-cursus-fermenteren` | `https://www.paypro.nl/producten/Online_Cursus_Fermenteren/90133/183297` | Approved landing artifact `15f10757-85fd-4f65-bb6b-6fb6703446f3` and blog artifact `21d47dc5-5354-4d50-9375-5ac519e83122` | 2026-08-27T22:00:00+00:00 (00:00 Europe/Amsterdam) |

Both products were verified through independent first-party redirects. The Yoga destination returned the account-issued PayPro URL with `utm_campaign=practice-happy-yoga`; the Fermenteren destination returned the account-issued PayPro URL with `utm_campaign=online-cursus-fermenteren`. Each check created one explicitly labelled `internal-verification` click event only.

The public portfolio index is available at `/site` and lists the original WegMetDieKilos page plus these two owner-approved product pages. The website publisher still exposes only policy-cleared, owner-approved landing and blog artifacts. Email and social drafts remain private and were not published or sent.
