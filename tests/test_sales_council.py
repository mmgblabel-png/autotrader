"""Tests for the deterministic, no-action sales-readiness council."""

from __future__ import annotations

from datetime import UTC, datetime

from campaign_automaton.hourly_review import HourlySalesReviewer
from campaign_automaton.models import (
    CampaignStatus,
    CampaignUpdate,
    RunRequest,
    TrackingEventCreate,
)
from campaign_automaton.sales_council import SalesReadinessCouncil


def _context(**overrides):
    context = {
        "data_quality": "verification_only",
        "observed": {"views": 0, "clicks": 0, "signups": 0, "conversions": 0},
        "verified_paypro_conversions": 0,
        "content": {"draft": 0, "approved": 1, "rejected": 0, "policy_blocked": 0},
        "approved_artifact_types": ["landing_page"],
        "product_fact_count": 2,
        "has_audience": True,
        "goal_count": 1,
    }
    context.update(overrides)
    return context


def test_council_runs_ten_dependency_ordered_advisors_without_external_action():
    report = SalesReadinessCouncil().evaluate(_context())
    findings = report["findings"]

    assert [finding["agent"] for finding in findings] == [
        "measurement_integrity",
        "funnel_stage",
        "attribution_integrity",
        "offer_facts",
        "audience_definition",
        "content_readiness",
        "landing_page_readiness",
        "consent_and_claims",
        "acquisition_handoff",
        "experiment_guardrail",
    ]
    assert all(finding["external_action"] is False for finding in findings)
    assert findings[1]["depends_on"] == ["measurement_integrity"]
    assert findings[-1]["depends_on"] == [finding["agent"] for finding in findings[:9]]
    assert report["final_recommendation"]["owner_approval_required"] is True
    assert report["final_recommendation"]["external_action"] is False
    assert report["final_recommendation"]["claims_sale"] is False


def test_council_allows_only_a_proposal_after_sufficient_observed_evidence():
    report = SalesReadinessCouncil().evaluate(
        _context(
            data_quality="observed_events",
            observed={"views": 100, "clicks": 20, "signups": 0, "conversions": 0},
        )
    )

    guardrail = report["findings"][-1]
    assert guardrail["status"] == "proposal_allowed"
    assert report["final_recommendation"]["allowed_change"] == "proposal_only"
    assert report["final_recommendation"]["external_action"] is False


def test_council_blocks_handoff_when_content_or_landing_page_is_missing():
    report = SalesReadinessCouncil().evaluate(
        _context(
            content={"draft": 1, "approved": 0, "rejected": 0, "policy_blocked": 1},
            approved_artifact_types=[],
        )
    )

    handoff = report["findings"][8]
    guardrail = report["findings"][9]
    assert handoff["status"] == "not_ready"
    assert "content_readiness" in handoff["evidence"]["blockers"]
    assert guardrail["status"] == "blocked_by_readiness"


def test_hourly_review_persists_council_findings_without_running_campaign_workflow(runtime):
    campaign = runtime.store.update_campaign(
        "wegmetdiekilos-bronze", CampaignUpdate(status=CampaignStatus.ACTIVE)
    )
    runtime.orchestrator.run_now(
        campaign["slug"], RunRequest(workflow="content", channels=["landing_page"], force=True)
    )
    artifact = runtime.store.list_artifacts(campaign["id"])[0]
    runtime.store.review_artifact(artifact["id"], "approved", "owner", "reviewed")
    runtime.store.record_tracking_event(
        TrackingEventCreate(
            campaign_slug=campaign["slug"],
            event_type="click",
            source="website-live-verification",
            medium="affiliate",
            event_id="verification-only-click",
        )
    )

    review, created = HourlySalesReviewer(runtime.store).review_campaign(
        campaign, now=datetime(2026, 8, 27, 15, 3, tzinfo=UTC)
    )

    assert created is True
    assert len(review["readiness"]["council"]["findings"]) == 10
    assert review["metrics"]["observed"]["clicks"] == 0
    assert review["recommendation"]["external_action"] is False
    assert len(runtime.store.list_runs(campaign["id"])) == 1
