"""Tests for the deterministic, approval-only hourly sales reviewer."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campaign_automaton.api import create_app
from campaign_automaton.hourly_review import HourlySalesReviewer
from campaign_automaton.models import CampaignStatus, CampaignUpdate, TrackingEventCreate
from campaign_automaton.runtime import build_runtime


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CAMPAIGN_CONFIG_PATH", str(root / "config" / "campaign.yaml"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("CONTROL_TOKEN", "test-control-token")
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-webhook-token")
    monkeypatch.setenv("PAYPRO_WEBHOOK_SECRET", "test-paypro-webhook-secret")
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("HEARTBEAT_ENABLED", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def _activate(runtime):
    return runtime.store.update_campaign(
        "wegmetdiekilos-bronze", CampaignUpdate(status=CampaignStatus.ACTIVE)
    )


def test_hourly_review_is_idempotent_and_excludes_verification_events(runtime):
    campaign = _activate(runtime)
    reviewer = HourlySalesReviewer(runtime.store)
    moment = datetime(2026, 8, 27, 9, 12, tzinfo=UTC)

    first, created = reviewer.review_campaign(campaign, now=moment)
    duplicate, duplicate_created = reviewer.review_campaign(campaign, now=moment)

    assert created is True
    assert duplicate_created is False
    assert duplicate["id"] == first["id"]
    assert first["readiness"]["data_quality"] == "no_events"
    assert first["recommendation"]["external_action"] is False
    assert first["recommendation"]["owner_approval_required"] is True

    runtime.store.record_tracking_event(
        TrackingEventCreate(
            campaign_slug=campaign["slug"],
            event_type="click",
            source="railway-live-verification",
            medium="affiliate",
            event_id="verification-click-1",
        )
    )
    verification_review, verification_created = reviewer.review_campaign(
        campaign, now=moment + timedelta(hours=1)
    )

    assert verification_created is True
    assert verification_review["readiness"]["data_quality"] == "verification_only"
    assert verification_review["metrics"]["observed"]["clicks"] == 0
    assert verification_review["readiness"]["sale_observed"] is False


def test_hourly_review_reports_observed_funnel_without_claiming_a_sale(runtime):
    campaign = _activate(runtime)
    reviewer = HourlySalesReviewer(runtime.store)
    runtime.store.record_tracking_event(
        TrackingEventCreate(
            campaign_slug=campaign["slug"],
            event_type="view",
            source="social",
            medium="affiliate",
            event_id="social-view-1",
        )
    )
    runtime.store.record_tracking_event(
        TrackingEventCreate(
            campaign_slug=campaign["slug"],
            event_type="click",
            source="social",
            medium="affiliate",
            event_id="social-click-1",
        )
    )

    review, created = reviewer.review_campaign(
        campaign, now=datetime(2026, 8, 27, 11, 5, tzinfo=UTC)
    )

    assert created is True
    assert review["readiness"]["data_quality"] == "observed_events"
    assert review["metrics"]["observed"] == {
        "views": 1,
        "clicks": 1,
        "signups": 0,
        "conversions": 0,
        "click_through_rate": 1.0,
        "conversion_rate": 0.0,
    }
    assert review["readiness"]["verified_paypro_conversions"] == 0
    assert review["recommendation"]["claims_sale"] is False


async def test_hourly_scheduler_runs_only_when_explicitly_enabled(settings):
    disabled_runtime = build_runtime(settings)
    _activate(disabled_runtime)
    disabled_tick = await disabled_runtime.scheduler.tick()
    assert disabled_tick["hourly_sales_review_ids"] == []

    enabled_runtime = build_runtime(replace(settings, hourly_sales_review_enabled=True))
    _activate(enabled_runtime)
    first_tick = await enabled_runtime.scheduler.tick()
    second_tick = await enabled_runtime.scheduler.tick()

    assert len(first_tick["hourly_sales_review_ids"]) == 1
    assert second_tick["hourly_sales_review_ids"] == []
    campaign = enabled_runtime.store.get_campaign("wegmetdiekilos-bronze")
    reviews = enabled_runtime.store.list_hourly_sales_reviews(campaign["id"])
    assert len(reviews) == 1


def test_hourly_review_endpoints_are_owner_only(client: TestClient):
    unauthenticated = client.get("/api/campaigns/wegmetdiekilos-bronze/hourly-reviews")
    assert unauthenticated.status_code == 401

    runtime = client.app.state.runtime
    campaign = _activate(runtime)
    review, created = runtime.scheduler.hourly_reviewer.review_campaign(
        campaign, now=datetime(2026, 8, 27, 13, 1, tzinfo=UTC)
    )
    assert created is True

    headers = {"X-Control-Token": "test-control-token"}
    history = client.get("/api/campaigns/wegmetdiekilos-bronze/hourly-reviews", headers=headers)
    latest = client.get(
        "/api/campaigns/wegmetdiekilos-bronze/hourly-reviews/latest", headers=headers
    )

    assert history.status_code == 200
    assert history.json()["reviews"][0]["id"] == review["id"]
    assert latest.status_code == 200
    assert latest.json()["id"] == review["id"]
    assert latest.json()["recommendation"]["external_action"] is False
