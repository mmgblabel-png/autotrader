"""Deterministic, internal hourly campaign review agent.

The reviewer reads only aggregate campaign records.  It does not invoke an LLM,
create campaign runs, edit artifacts, publish content, send messages, buy traffic,
or interact with PayPro beyond the first-party events already stored locally.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from campaign_automaton.sales_council import SalesReadinessCouncil
from campaign_automaton.store import SQLiteStore

VERIFICATION_SOURCES = frozenset(
    {"railway-live-verification", "website-live-verification", "internal-verification"}
)
FUNNEL_KEYS = ("views", "clicks", "signups", "conversions")
MINIMUM_OBSERVED_VIEWS = 100
MINIMUM_OBSERVED_CLICKS = 20


class HourlySalesReviewer:
    """Create factual, durable hourly reviews with a human approval boundary."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self.council = SalesReadinessCouncil()

    def review_campaign(self, campaign: dict[str, Any], now: datetime | None = None) -> tuple[dict[str, Any], bool]:
        """Store one idempotent review for the campaign's current UTC hour."""
        moment = (now or datetime.now(UTC)).astimezone(UTC)
        hour_bucket = moment.replace(minute=0, second=0, microsecond=0).isoformat()
        existing = self.store.get_hourly_sales_review(campaign["id"], hour_bucket)
        if existing is not None:
            return existing, False

        totals = self.store.campaign_metrics(campaign["id"])
        observed = _observed_metrics(totals)
        verified_conversions = _verified_paypro_conversions(totals)
        prior = self.store.latest_hourly_sales_review(campaign["id"])
        prior_observed = (
            prior.get("metrics", {}).get("observed", {}) if prior else {}
        )
        change = {
            key: max(0, int(observed[key]) - int(prior_observed.get(key, 0)))
            for key in FUNNEL_KEYS
        }
        readiness = self._readiness(campaign, totals, observed, verified_conversions)
        council = self.council.evaluate(
            {
                "data_quality": readiness["data_quality"],
                "observed": observed,
                "verified_paypro_conversions": verified_conversions,
                "content": readiness["content"],
                "approved_artifact_types": readiness["approved_artifact_types"],
                "product_fact_count": len(campaign["product_facts"]),
                "has_audience": bool(campaign["audience"].strip()),
                "goal_count": len(campaign["goals"]),
            }
        )
        readiness["council"] = council
        recommendation = council["final_recommendation"]
        metrics = {
            "all_tracked": _metric_summary(totals),
            "observed": _metric_summary(observed),
            "change_since_prior_review": change,
        }
        review, created = self.store.create_hourly_sales_review(
            campaign_id=campaign["id"],
            hour_bucket=hour_bucket,
            metrics=metrics,
            readiness=readiness,
            recommendation=recommendation,
        )
        if created:
            self.store.audit(
                campaign["id"],
                "hourly_sales_reviewer",
                "sales_review.created",
                "hourly_sales_review",
                review["id"],
                {
                    "hour_bucket": hour_bucket,
                    "data_quality": readiness["data_quality"],
                    "verified_paypro_conversions": verified_conversions,
                    "external_action": False,
                },
            )
        return review, created

    def _readiness(
        self,
        campaign: dict[str, Any],
        totals: dict[str, Any],
        observed: dict[str, int],
        verified_conversions: int,
    ) -> dict[str, Any]:
        artifacts = self.store.list_artifacts(campaign["id"], limit=500)
        artifact_counts = {
            "draft": sum(artifact["status"] == "draft" for artifact in artifacts),
            "approved": sum(artifact["status"] == "approved" for artifact in artifacts),
            "rejected": sum(artifact["status"] == "rejected" for artifact in artifacts),
            "policy_blocked": sum(
                not artifact.get("policy", {}).get("allowed", False) for artifact in artifacts
            ),
        }
        has_verification_events = any(
            str(row.get("source", "")).lower() in VERIFICATION_SOURCES
            for row in totals.get("by_source", [])
        )
        if sum(observed.values()) > 0:
            data_quality = "observed_events"
        elif has_verification_events:
            data_quality = "verification_only"
        else:
            data_quality = "no_events"
        approved_artifact_types = sorted(
            {
                artifact["artifact_type"]
                for artifact in artifacts
                if artifact["status"] == "approved"
                and artifact.get("policy", {}).get("allowed", False)
            }
        )
        return {
            "data_quality": data_quality,
            "approved_artifact_types": approved_artifact_types,
            "observed_evidence": {
                "minimum_views": MINIMUM_OBSERVED_VIEWS,
                "minimum_clicks": MINIMUM_OBSERVED_CLICKS,
                "views_ready": observed["views"] >= MINIMUM_OBSERVED_VIEWS,
                "clicks_ready": observed["clicks"] >= MINIMUM_OBSERVED_CLICKS,
            },
            "content": artifact_counts,
            "affiliate_attribution_requires_owner_check": True,
            "verified_paypro_conversions": verified_conversions,
            "sale_observed": verified_conversions > 0,
            "public_action_performed": False,
            "campaign_status": campaign["status"],
        }


def _observed_metrics(metrics: dict[str, Any]) -> dict[str, int]:
    observed = {key: 0 for key in FUNNEL_KEYS}
    for row in metrics.get("by_source", []):
        if str(row.get("source", "")).lower() in VERIFICATION_SOURCES:
            continue
        event_type = str(row.get("event_type", "")).rsplit(".", maxsplit=1)[-1].lower()
        metric_key = {
            "view": "views",
            "click": "clicks",
            "signup": "signups",
            "conversion": "conversions",
        }.get(event_type)
        if metric_key:
            observed[metric_key] += int(row.get("count") or 0)
    return observed


def _verified_paypro_conversions(metrics: dict[str, Any]) -> int:
    return sum(
        int(row.get("count") or 0)
        for row in metrics.get("by_source", [])
        if str(row.get("source", "")).lower() == "paypro"
        and str(row.get("event_type", "")).rsplit(".", maxsplit=1)[-1].lower() == "conversion"
    )


def _metric_summary(metrics: dict[str, Any]) -> dict[str, int | float]:
    views = int(metrics.get("views") or 0)
    clicks = int(metrics.get("clicks") or 0)
    conversions = int(metrics.get("conversions") or 0)
    return {
        "views": views,
        "clicks": clicks,
        "signups": int(metrics.get("signups") or 0),
        "conversions": conversions,
        "click_through_rate": round(clicks / views, 4) if views else 0.0,
        "conversion_rate": round(conversions / clicks, 4) if clicks else 0.0,
    }


def _recommendation(
    readiness: dict[str, Any], observed: dict[str, int], verified_conversions: int
) -> dict[str, Any]:
    """Return one conservative next step; it is never an execution instruction."""
    content = readiness["content"]
    if readiness["data_quality"] in {"no_events", "verification_only"}:
        action = "Prepare one owner-approved, consent-respecting distribution handoff."
        rationale = (
            "No observed customer traffic is available yet; verification checks are not demand evidence."
        )
    elif observed["views"] < MINIMUM_OBSERVED_VIEWS:
        action = "Collect more observed traffic through one already-approved asset before changing copy."
        rationale = "The campaign has fewer than 100 observed views, so copy changes would be premature."
    elif observed["clicks"] < MINIMUM_OBSERVED_CLICKS:
        action = "Review the existing call-to-action and distribution context; keep one version as control."
        rationale = "The campaign has fewer than 20 observed clicks, so conversion conclusions are unreliable."
    elif verified_conversions == 0:
        action = "Propose one reversible, owner-reviewed experiment for a single approved channel."
        rationale = "There is enough basic traffic evidence to form a hypothesis, but no verified conversion."
    else:
        action = "Review verified conversion attribution and preserve the current asset as the control."
        rationale = "A verified PayPro conversion exists; further changes need an explicit measurement plan."

    if content["approved"] == 0:
        action = "Review one policy-cleared draft before considering any distribution."
        rationale = "No approved content is available for a compliant handoff."
    elif content["draft"] > 0:
        rationale += " There are draft artifacts awaiting owner review."

    return {
        "action": action,
        "rationale": rationale,
        "owner_approval_required": True,
        "external_action": False,
        "claims_sale": False,
    }
