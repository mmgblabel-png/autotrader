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
