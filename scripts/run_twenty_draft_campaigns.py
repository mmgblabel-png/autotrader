"""Generate reviewable content drafts for the 20 local Amazon product campaigns.

This command is deliberately draft-only. It does not call a social network, email
provider, ad platform, or publishing endpoint, and it does not approve artifacts.
"""

from __future__ import annotations

import argparse

from campaign_automaton.config import load_settings
from campaign_automaton.models import RunRequest
from campaign_automaton.runtime import build_runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Run draft-only content generation for product campaigns.")
    parser.add_argument("--slug", help="Run only the specified campaign slug.")
    parser.add_argument(
        "--workflow",
        choices=["content", "marketing"],
        default="content",
        help="Run a complete draft content workflow or refresh marketing drafts only.",
    )
    args = parser.parse_args()
    settings = load_settings()
    if not settings.draft_only:
        raise ValueError("DRAFT_ONLY must remain true while generating marketing drafts.")
    runtime = build_runtime(settings)
    campaigns = sorted(
        runtime.store.list_campaigns(),
        key=lambda campaign: int(campaign.get("metadata", {}).get("priority", 999)),
    )
    selected = [
        campaign
        for campaign in campaigns
        if campaign.get("metadata", {}).get("mode") == "draft_only"
        and "priority" in campaign.get("metadata", {})
    ]
    if args.slug:
        selected = [campaign for campaign in selected if campaign["slug"] == args.slug]
    elif len(selected) != 20:
        raise ValueError(f"Expected 20 draft-only product campaigns; found {len(selected)}.")
    if not selected:
        raise ValueError("No matching draft-only product campaign was found.")
    total_artifacts = 0
    blocked_artifacts = 0
    for campaign in selected:
        run = runtime.orchestrator.run_now(
            campaign["slug"],
            RunRequest(workflow=args.workflow, force=True),
        )
        summary = run.get("summary", {})
        total_artifacts += int(summary.get("artifacts_created", 0))
        blocked_artifacts += int(summary.get("blocked_artifacts", 0))
        print(f"{campaign['slug']}: {run['status']} ({summary.get('artifacts_created', 0)} artifacts)")
    print(f"Completed {len(selected)} draft-only campaign runs: {total_artifacts} artifacts, {blocked_artifacts} policy-blocked.")
    print("No artifacts were approved, posted, emailed, or otherwise published.")


if __name__ == "__main__":
    main()
