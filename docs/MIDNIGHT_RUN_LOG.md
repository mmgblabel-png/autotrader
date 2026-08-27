# Midnight Campaign Run Verification Log

**Capture time:** 2026-08-26T22:01:46Z  
**Campaign:** `wegmetdiekilos-bronze`  
**Requested local run time:** 2026-08-27 00:00 Europe/Amsterdam

## Result

The service was healthy (`status=ok`, persistent database healthy, 30-second heartbeat running, no heartbeat error), but the midnight campaign workflow did **not** create a new run. The heartbeat tick immediately after the expected time reported no executed runs. The campaign was nonetheless advanced to `next_run_at=2026-08-27T22:00:00+00:00` (2026-08-28 00:00 Europe/Amsterdam).

## Root cause

The scheduler used the generic same-day `full_campaign` idempotency key. An earlier full campaign workflow had already run on 2026-08-26 UTC during activation, so the midnight scheduler correctly avoided creating a duplicate under that key, but incorrectly advanced the next schedule. No draft was published, no artifact was approved, and no external content changed.

## Runtime evidence

| Check | Result |
|---|---|
| Health endpoint | `ok`; database healthy |
| Heartbeat after scheduled time | Completed successfully; `executed_runs=[]` |
| Latest new workflow at capture | None; latest full campaign was the prior activation-time run |
| Current campaign state | Active; cron `0 0 * * *`; next run moved to the following midnight |
| Existing draft artifacts | 8 from the prior full campaign; all policy-allowed, none automatically published |
| Analytics | 1 verification view, 2 verification clicks, 0 conversions; insufficient to judge performance |
| Railway deployment | The tested scheduler correction deployment became active successfully after the capture |

## Correction status

Commit `9894c3d` assigns each scheduled occurrence a stable occurrence-specific idempotency key. The full test suite passed with a regression test that proves a scheduled occurrence is no longer suppressed by a prior same-day manual run. A safe catch-up workflow is required to replace the missed midnight run and will generate drafts only; it must not approve or publish content.


## Verified catch-up run

After the tested correction was deployed, a controlled catch-up full-campaign workflow was run with occurrence key `scheduler-catchup-2026-08-27T0000-Europe-Amsterdam`. Run `91551cd1-9283-4a66-91b2-7abb6168f351` completed at `2026-08-26T22:05:50.073848+00:00` with status `awaiting_approval`.

The run invoked Research, SEO, Marketing, and Analytics agents and generated eight new artifacts. All eight remain `draft`; every artifact was policy-allowed. The landing-page and blog drafts carry the expected medical-context warning and disclosure. No artifact was approved, and the publisher still exposes only the two previously approved initial website artifacts.

The repaired scheduler is now active in Railway under commit `9894c3d`. The next recurring run remains scheduled for `2026-08-27T22:00:00+00:00` (`2026-08-28 00:00 Europe/Amsterdam`), where its occurrence-specific key will be independent of earlier same-day manual or catch-up runs.
