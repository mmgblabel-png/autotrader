from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campaign_automaton.api import create_app


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
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("HEARTBEAT_ENABLED", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def control() -> dict[str, str]:
    return {"X-Control-Token": "test-control-token"}


def test_health_is_public_and_ready(client: TestClient):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["database_ok"] is True
    assert payload["llm_mode"] == "deterministic"


def test_control_endpoints_require_token(client: TestClient):
    assert client.get("/api/campaigns").status_code == 401
    assert client.get("/api/campaigns", headers={"X-Control-Token": "wrong"}).status_code == 401
    response = client.get("/api/campaigns", headers=control())
    assert response.status_code == 200
    assert response.json()["campaigns"][0]["slug"] == "wegmetdiekilos-bronze"


def test_run_artifact_and_review_flow(client: TestClient):
    run = client.post(
        "/api/campaigns/wegmetdiekilos-bronze/runs",
        headers=control(),
        json={"workflow": "content", "channels": ["blog", "email"], "force": True},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "awaiting_approval"
    artifacts = client.get(
        "/api/campaigns/wegmetdiekilos-bronze/artifacts", headers=control()
    )
    assert artifacts.status_code == 200
    rows = artifacts.json()["artifacts"]
    assert rows
    allowed = next(item for item in rows if item["policy"]["allowed"])
    reviewed = client.post(
        f"/api/artifacts/{allowed['id']}/review",
        headers=control(),
        json={"decision": "approved", "reviewer": "test-owner", "notes": "checked"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "approved"


def test_webhook_deduplicates_external_event(client: TestClient):
    payload = {
        "provider": "test-provider",
        "event": {
            "campaign_slug": "wegmetdiekilos-bronze",
            "event_type": "conversion",
            "source": "blog",
            "medium": "affiliate",
            "event_id": "external-1",
            "value": 19.0,
            "metadata": {},
        },
    }
    headers = {"X-Webhook-Token": "test-webhook-token"}
    first = client.post("/api/webhooks/events", headers=headers, json=payload)
    second = client.post("/api/webhooks/events", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    metrics = client.get(
        "/api/campaigns/wegmetdiekilos-bronze/analytics", headers=control()
    )
    assert metrics.json()["conversions"] == 1


def test_tracked_redirect_records_click_and_preserves_destination(client: TestClient):
    response = client.get(
        "/r/wegmetdiekilos-bronze?src=social&content=post-1",
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://www.paypro.nl/producten/")
    assert "utm_source=social" in location
    metrics = client.get(
        "/api/campaigns/wegmetdiekilos-bronze/analytics", headers=control()
    ).json()
    assert metrics["clicks"] == 1


def test_clone_campaign_and_decide_optimization(client: TestClient):
    cloned = client.post(
        "/api/campaigns/wegmetdiekilos-bronze/clone",
        headers=control(),
        json={
            "name": "Nieuwe campagne",
            "slug": "nieuwe-campagne",
            "product_name": "Nieuw product",
            "product_url": "https://example.com/product",
            "reset_product_facts": True,
        },
    )
    assert cloned.status_code == 201
    assert cloned.json()["product_facts"] == []

    run = client.post(
        "/api/campaigns/wegmetdiekilos-bronze/runs",
        headers=control(),
        json={"workflow": "analytics", "force": True},
    )
    assert run.status_code == 200
    proposals = client.get(
        "/api/campaigns/wegmetdiekilos-bronze/optimizations", headers=control()
    ).json()["proposals"]
    assert proposals
    decision = client.post(
        f"/api/optimizations/{proposals[0]['id']}/decision",
        headers=control(),
        json={"decision": "accepted", "reviewer": "owner", "notes": "test"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "accepted"


@pytest.fixture()
def publisher_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "publisher.db"))
    monkeypatch.setenv("CAMPAIGN_CONFIG_PATH", str(root / "config" / "campaign.yaml"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("CONTROL_TOKEN", "test-control-token")
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-webhook-token")
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("HEARTBEAT_ENABLED", "false")
    monkeypatch.setenv("WEBSITE_ENABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def test_public_site_is_disabled_by_default(client: TestClient):
    response = client.get("/site/wegmetdiekilos-bronze")
    assert response.status_code == 404


def test_public_site_renders_approved_artifacts_only(publisher_client: TestClient):
    run = publisher_client.post(
        "/api/campaigns/wegmetdiekilos-bronze/runs",
        headers=control(),
        json={"workflow": "content", "channels": ["landing_page", "blog"], "force": True},
    )
    assert run.status_code == 200
    artifacts = publisher_client.get(
        "/api/campaigns/wegmetdiekilos-bronze/artifacts", headers=control()
    ).json()["artifacts"]
    draft_blog = next(item for item in artifacts if item["artifact_type"] == "blog_article")
    assert publisher_client.get(
        f"/site/wegmetdiekilos-bronze/articles/{draft_blog['id']}"
    ).status_code == 404

    for artifact in artifacts:
        if artifact["artifact_type"] in {"blog_article", "landing_page_copy"}:
            reviewed = publisher_client.post(
                f"/api/artifacts/{artifact['id']}/review",
                headers=control(),
                json={"decision": "approved", "reviewer": "test-owner", "notes": "reviewed"},
            )
            assert reviewed.status_code == 200

    site = publisher_client.get("/site/wegmetdiekilos-bronze")
    assert site.status_code == 200
    assert "Geen wondermiddel en geen garantie" in site.text
    assert "Affiliate disclosure" in site.text
    assert "/r/wegmetdiekilos-bronze?src=website-home" in site.text

    article = publisher_client.get(
        f"/site/wegmetdiekilos-bronze/articles/{draft_blog['id']}"
    )
    assert article.status_code == 200
    assert "Gezond afvallen begint met een plan" in article.text
    status = publisher_client.get("/api/publisher/status", headers=control())
    assert status.status_code == 200
    assert status.json()["approved_artifact_count"] == 2



def test_public_portfolio_lists_active_approved_campaigns_only(publisher_client: TestClient):
    empty_portfolio = publisher_client.get("/site")
    assert empty_portfolio.status_code == 200
    assert "WegMetDieKilos" not in empty_portfolio.text

    activated = publisher_client.patch(
        "/api/campaigns/wegmetdiekilos-bronze",
        headers=control(),
        json={"status": "active"},
    )
    assert activated.status_code == 200
    run = publisher_client.post(
        "/api/campaigns/wegmetdiekilos-bronze/runs",
        headers=control(),
        json={"workflow": "content", "channels": ["landing_page"], "force": True},
    )
    assert run.status_code == 200
    artifacts = publisher_client.get(
        "/api/campaigns/wegmetdiekilos-bronze/artifacts", headers=control()
    ).json()["artifacts"]
    landing = next(item for item in artifacts if item["artifact_type"] == "landing_page_copy")
    approved = publisher_client.post(
        f"/api/artifacts/{landing['id']}/review",
        headers=control(),
        json={"decision": "approved", "reviewer": "test-owner", "notes": "checked"},
    )
    assert approved.status_code == 200

    portfolio = publisher_client.get("/site")
    assert portfolio.status_code == 200
    assert "WegMetDieKilos – Bronze Plan" in portfolio.text
    assert "/site/wegmetdiekilos-bronze" in portfolio.text
