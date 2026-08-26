"""Owner-facing command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from campaign_automaton.models import (
    ApprovalRequest,
    ArtifactStatus,
    CampaignStatus,
    CampaignUpdate,
    Channel,
    RunRequest,
)
from campaign_automaton.runtime import build_runtime


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="campaign-automaton",
        description="Approval-gated PayPro campaign agent runtime",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the FastAPI service")
    serve.add_argument("--host", default="0.0.0.0")  # noqa: S104 - server entry point
    serve.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))

    sub.add_parser("init", help="Initialize the database and default campaign")
    sub.add_parser("campaigns", help="List campaigns")

    status = sub.add_parser("set-status", help="Set campaign lifecycle status")
    status.add_argument("--campaign", default="wegmetdiekilos-bronze")
    status.add_argument("--status", choices=[item.value for item in CampaignStatus], required=True)

    run = sub.add_parser("run", help="Run an agent workflow now")
    run.add_argument("--campaign", default="wegmetdiekilos-bronze")
    run.add_argument(
        "--workflow",
        default="full_campaign",
        choices=["full_campaign", "research", "seo", "content", "analytics"],
    )
    run.add_argument("--channels", nargs="*", choices=[item.value for item in Channel])
    run.add_argument("--force", action="store_true")

    artifacts = sub.add_parser("artifacts", help="List generated artifacts")
    artifacts.add_argument("--campaign", default="wegmetdiekilos-bronze")
    artifacts.add_argument("--status", choices=[item.value for item in ArtifactStatus])

    analytics = sub.add_parser("analytics", help="Show campaign metrics")
    analytics.add_argument("--campaign", default="wegmetdiekilos-bronze")

    review = sub.add_parser("review", help="Approve or reject an artifact")
    review.add_argument("artifact_id")
    review.add_argument("--decision", choices=["approved", "rejected"], required=True)
    review.add_argument("--reviewer", default="owner")
    review.add_argument("--notes", default="")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("campaign_automaton.api:app", host=args.host, port=args.port)
        return
    runtime = build_runtime()
    if args.command == "init":
        _print(
            {
                "database": str(runtime.settings.database_path),
                "campaigns": runtime.store.list_campaigns(),
                "affiliate": runtime.links.affiliate_status(),
                "llm_mode": runtime.llm.mode,
            }
        )
    elif args.command == "campaigns":
        _print(runtime.store.list_campaigns())
    elif args.command == "set-status":
        _print(
            runtime.store.update_campaign(
                args.campaign,
                CampaignUpdate(status=CampaignStatus(args.status)),
            )
        )
    elif args.command == "run":
        channels = [Channel(item) for item in args.channels] if args.channels else None
        _print(
            runtime.orchestrator.run_now(
                args.campaign,
                RunRequest(workflow=args.workflow, channels=channels, force=args.force),
            )
        )
    elif args.command == "artifacts":
        campaign = runtime.store.get_campaign(args.campaign)
        _print(runtime.store.list_artifacts(campaign["id"], args.status))
    elif args.command == "analytics":
        campaign = runtime.store.get_campaign(args.campaign)
        _print(runtime.store.campaign_metrics(campaign["id"]))
    elif args.command == "review":
        payload = ApprovalRequest(
            decision=ArtifactStatus(args.decision), reviewer=args.reviewer, notes=args.notes
        )
        artifact = runtime.store.get_artifact(args.artifact_id)
        if payload.decision == ArtifactStatus.APPROVED and not artifact["policy"].get(
            "allowed", False
        ):
            raise SystemExit("Artifact has blocking policy findings and cannot be approved.")
        _print(
            runtime.store.review_artifact(
                args.artifact_id, payload.decision, payload.reviewer, payload.notes
            )
        )


if __name__ == "__main__":
    main()
