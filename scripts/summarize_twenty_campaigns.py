"""Summarize locally stored 20-product draft campaign artifacts without modifying them."""

from __future__ import annotations

import json

from campaign_automaton.runtime import build_runtime


def main() -> None:
    runtime = build_runtime()
    rows: list[dict[str, object]] = []
    totals = {"campaigns": 0, "artifacts": 0, "allowed": 0, "blocked": 0}
    for campaign in sorted(
        runtime.store.list_campaigns(),
        key=lambda item: int(item.get("metadata", {}).get("priority", 999)),
    ):
        metadata = campaign.get("metadata", {})
        if metadata.get("mode") != "draft_only" or "priority" not in metadata:
            continue
        artifacts = runtime.store.list_artifacts(campaign["id"], limit=100)
        allowed = sum(1 for item in artifacts if item.get("policy", {}).get("allowed", False))
        blocked = len(artifacts) - allowed
        rows.append(
            {
                "priority": metadata["priority"],
                "slug": campaign["slug"],
                "category": metadata["category"],
                "artifacts": len(artifacts),
                "allowed": allowed,
                "blocked": blocked,
                "status": campaign["status"],
            }
        )
        totals["campaigns"] += 1
        totals["artifacts"] += len(artifacts)
        totals["allowed"] += allowed
        totals["blocked"] += blocked
    print(json.dumps({"totals": totals, "campaigns": rows}, indent=2))


if __name__ == "__main__":
    main()
