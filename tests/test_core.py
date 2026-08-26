from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from campaign_automaton.models import (
    CampaignStatus,
    CampaignUpdate,
    RunRequest,
    TrackingEventCreate,
)
from campaign_automaton.runtime import build_runtime


def test_default_campaign_is_seeded(runtime):
    campaign = runtime.store.get_campaign("wegmetdiekilos-bronze")
    assert campaign["product_name"] == "WegMetDieKilos – Bronze Plan"
    assert "blog" in campaign["channels"]
    assert campaign["status"] == "draft"


def test_full_workflow_creates_agent_artifacts(runtime):
    result = runtime.orchestrator.run_now(
        "wegmetdiekilos-bronze", RunRequest(workflow="full_campaign", force=True)
    )
    assert result["status"] == "awaiting_approval"
    assert result["summary"]["agents"] == [
        "ResearchAgent",
        "SEOAgent",
        "MarketingAgent",
        "AnalyticsAgent",
    ]
    campaign = runtime.store.get_campaign("wegmetdiekilos-bronze")
    artifacts = runtime.store.list_artifacts(campaign["id"])
    assert len(artifacts) >= 8
    marketing = [item for item in artifacts if item["agent"] == "MarketingAgent"]
    assert marketing
    assert all("commissie ontvangen" in item["content"] for item in marketing)
    assert all(item["metadata"]["deterministic"] is True for item in artifacts)


def test_daily_idempotency_reuses_completed_run(runtime):
    request = RunRequest(workflow="analytics", force=False)
    first = runtime.orchestrator.run_now("wegmetdiekilos-bronze", request)
    second = runtime.orchestrator.run_now("wegmetdiekilos-bronze", request)
    assert first["id"] == second["id"]


def test_policy_blocks_guaranteed_claim(runtime):
    evaluated = runtime.policy.evaluate_content(
        "Gegarandeerd 10 kilo in 2 weken zonder moeite!",
        channel="social",
        sales_intent=True,
    )
    assert evaluated.result.allowed is False
    assert any(
        item.code == "unsupported_weight_loss_claim" for item in evaluated.result.findings
    )


def test_action_policy_blocks_unsolicited_outreach(runtime):
    result = runtime.policy.evaluate_action("unsolicited_email", {})
    assert result.allowed is False


def test_affiliate_template_substitution(settings, runtime):
    object.__setattr__(
        settings,
        "paypro_affiliate_url_template",
        "https://affiliate.example/{affiliate_id}?target={product_url}",
    )
    campaign = runtime.store.get_campaign("wegmetdiekilos-bronze")
    target = runtime.links.destination(campaign, "blog", "artifact-1")
    assert "affiliate-123" in target
    assert "utm_campaign=wegmetdiekilos-bronze" in target


def test_tracking_is_idempotent_and_metrics_are_aggregated(runtime):
    event = TrackingEventCreate(
        campaign_slug="wegmetdiekilos-bronze",
        event_type="conversion",
        source="email",
        medium="affiliate",
        event_id="paypro-event-1",
        value=12.5,
    )
    first, created_first = runtime.store.record_tracking_event(event)
    second, created_second = runtime.store.record_tracking_event(event)
    assert created_first is True
    assert created_second is False
    assert first["id"] == second["id"]
    campaign = runtime.store.get_campaign("wegmetdiekilos-bronze")
    metrics = runtime.store.campaign_metrics(campaign["id"])
    assert metrics["conversions"] == 1
    assert metrics["value"] == 12.5


def test_campaign_clone_resets_product_facts_and_not_history(runtime):
    from campaign_automaton.models import CampaignCloneRequest

    source = runtime.store.get_campaign("wegmetdiekilos-bronze")
    clone = runtime.store.clone_campaign(
        source["slug"],
        CampaignCloneRequest(
            name="Nieuwe campagne",
            slug="nieuwe-campagne",
            product_name="Nieuw product",
            product_url="https://example.com/product",
            reset_product_facts=True,
        ),
        "https://example.com/product",
    )
    assert clone["product_facts"] == []
    assert clone["metadata"]["cloned_from"] == source["slug"]
    assert runtime.store.list_runs(clone["id"]) == []
    assert runtime.store.campaign_metrics(clone["id"])["clicks"] == 0


def test_optimization_proposal_requires_owner_decision(runtime):
    run = runtime.orchestrator.run_now(
        "wegmetdiekilos-bronze", RunRequest(workflow="analytics", force=True)
    )
    campaign = runtime.store.get_campaign("wegmetdiekilos-bronze")
    proposals = runtime.store.list_optimization_proposals(campaign["id"])
    assert proposals and proposals[0]["status"] == "proposed"
    decided = runtime.store.decide_optimization(
        proposals[0]["id"], "accepted", "owner", "Run as a controlled test"
    )
    assert decided["status"] == "accepted"
    assert decided["run_id"] == run["id"]


def test_tracking_metadata_rejects_direct_identifiers():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TrackingEventCreate(
            campaign_slug="wegmetdiekilos-bronze",
            event_type="click",
            metadata={"email": "person@example.com"},
        )
    with pytest.raises(ValidationError):
        TrackingEventCreate(
            campaign_slug="wegmetdiekilos-bronze",
            event_type="click",
            metadata={"note": "contact person@example.com"},
        )
    allowed = TrackingEventCreate(
        campaign_slug="wegmetdiekilos-bronze",
        event_type="click",
        metadata={"experiment": "cta-a", "cohort": "anonymous-1"},
    )
    assert allowed.metadata["experiment"] == "cta-a"


async def test_heartbeat_executes_queued_run_once(runtime):
    run, created = runtime.orchestrator.queue_run(
        "wegmetdiekilos-bronze",
        RunRequest(workflow="analytics", force=True),
    )
    assert created is True
    result = await runtime.scheduler.tick()
    assert result["status"] == "ok"
    finished = runtime.store.get_run(run["id"])
    assert finished["status"] == "awaiting_approval"
    second = await runtime.scheduler.tick()
    assert second["executed_runs"] == []
    assert len(runtime.store.latest_heartbeats()) == 2


async def test_due_campaign_schedule_uses_europe_amsterdam(settings):
    live_runtime = build_runtime(replace(settings, auto_run_due_campaigns=True))
    live_runtime.store.update_campaign(
        "wegmetdiekilos-bronze", CampaignUpdate(status=CampaignStatus.ACTIVE)
    )
    result = await live_runtime.scheduler.tick()
    assert result["status"] == "ok"
    campaign = live_runtime.store.get_campaign("wegmetdiekilos-bronze")
    next_run = datetime.fromisoformat(campaign["next_run_at"])
    local_next_run = next_run.astimezone(ZoneInfo("Europe/Amsterdam"))
    assert local_next_run.hour == 9
    assert next_run.tzinfo is not None


def test_policy_allows_explicit_negation_but_blocks_positive_claim(runtime):
    allowed = runtime.policy.evaluate_content(
        "Geen wondermiddel en geen garantie op een bepaald resultaat.",
        channel="landing_page",
        sales_intent=True,
    )
    blocked = runtime.policy.evaluate_content(
        "Dit wondermiddel geeft gegarandeerd resultaat.",
        channel="landing_page",
        sales_intent=True,
    )
    assert allowed.result.allowed is True
    assert blocked.result.allowed is False


async def test_scheduled_occurrence_has_its_own_idempotency_key(settings):
    live_runtime = build_runtime(replace(settings, auto_run_due_campaigns=True))
    manual = live_runtime.orchestrator.run_now(
        "wegmetdiekilos-bronze", RunRequest(workflow="full_campaign", force=False)
    )
    campaign = live_runtime.store.get_campaign("wegmetdiekilos-bronze")
    live_runtime.store.update_campaign(
        campaign["slug"], CampaignUpdate(status=CampaignStatus.ACTIVE)
    )
    live_runtime.store.set_next_run(campaign["id"], "2000-01-01T00:00:00+00:00")

    tick = await live_runtime.scheduler.tick()

    assert tick["status"] == "ok"
    assert len(tick["executed_runs"]) == 1
    runs = live_runtime.store.list_runs(campaign["id"])
    full_campaign_runs = [item for item in runs if item["workflow"] == "full_campaign"]
    assert len(full_campaign_runs) == 2
    assert manual["id"] != tick["executed_runs"][0]
