from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from campaign_automaton.api import create_app

SLUG = "owala-freesip-24oz"
SPECIAL_LINK = "https://www.amazon.com/dp/B0BZYCJK89?tag=spmg00-20"


def configure_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, website_enabled: bool = False,
    special_link: str = SPECIAL_LINK,
) -> None:
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CAMPAIGN_CONFIG_PATH", str(root / "config" / "campaign.yaml"))
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("CONTROL_TOKEN", "test-control-token")
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-webhook-token")
    monkeypatch.setenv("AFFILIATE_PROVIDER", "amazon")
    monkeypatch.setenv("AMAZON_PRODUCT_URL", "https://www.amazon.com/dp/B0BZYCJK89")
    monkeypatch.setenv("AMAZON_ASSOCIATE_URL", special_link)
    monkeypatch.setenv(
        "AFFILIATE_DISCLOSURE",
        "Disclosure: As an Amazon Associate I earn from qualifying purchases. (paid link)",
    )
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    monkeypatch.setenv("HEARTBEAT_ENABLED", "false")
    monkeypatch.setenv("WEBSITE_ENABLED", str(website_enabled).lower())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    configure_environment(tmp_path, monkeypatch)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def publisher_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    configure_environment(tmp_path, monkeypatch, website_enabled=True)
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


def test_config_status_identifies_direct_amazon_link_requirement(client: TestClient):
    response = client.get("/api/config/status", headers=control())
    assert response.status_code == 200
    affiliate = response.json()["affiliate"]
    assert affiliate["provider"] == "amazon"
    assert affiliate["direct_links_only"] is True
    assert affiliate["special_link_configured"] is True
    assert affiliate["ready"] is True


def test_public_snapshot_is_token_free_and_aggregated(client: TestClient):
    activated = client.patch(f"/api/campaigns/{SLUG}", headers=control(), json={"status": "active"})
    assert activated.status_code == 200
    response = client.get("/api/public/farm-snapshot")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == 1
    assert payload["refresh_interval_seconds"] == 60
    assert payload["lifecycle"] == {"views": 0, "clicks": 0, "signups": 0, "conversions": 0}
    campaign = payload["campaigns"][0]
    assert campaign["slug"] == SLUG
    assert campaign["product_name"] == "Owala FreeSip Stainless Steel Water Bottle, 24 oz"
    assert "product_url" not in campaign
    assert "metadata" not in campaign


def test_public_snapshot_uses_allowlisted_source_aggregation(client: TestClient):
    client.patch(f"/api/campaigns/{SLUG}", headers=control(), json={"status": "active"})
    recorded = client.post(
        "/api/events",
        headers=control(),
        json={
            "campaign_slug": SLUG,
            "event_type": "click",
            "source": "social",
            "medium": "affiliate",
            "metadata": {"tracking": "test"},
        },
    )
    assert recorded.status_code == 201
    snapshot = client.get("/api/public/farm-snapshot").json()
    assert snapshot["source_breakdown"] == [
        {"source": "Social media", "metrics": {"views": 0, "clicks": 1, "signups": 0, "conversions": 0}}
    ]
    assert snapshot["attribution_breakdown"][0]["campaign_slug"] == SLUG
    assert snapshot["attribution_breakdown"][0]["content"] == "Unlabeled asset"


def test_control_endpoints_require_token(client: TestClient):
    assert client.get("/api/campaigns").status_code == 401
    assert client.get("/api/campaigns", headers={"X-Control-Token": "wrong"}).status_code == 401
    response = client.get("/api/campaigns", headers=control())
    assert response.status_code == 200
    assert response.json()["campaigns"][0]["slug"] == SLUG


def test_run_creates_disclosed_direct_link_drafts_that_require_review(client: TestClient):
    run = client.post(
        f"/api/campaigns/{SLUG}/runs",
        headers=control(),
        json={"workflow": "content", "channels": ["blog", "social"], "force": True},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "awaiting_approval"
    artifacts = client.get(f"/api/campaigns/{SLUG}/artifacts", headers=control()).json()["artifacts"]
    marketing = [item for item in artifacts if item["agent"] == "MarketingAgent"]
    assert len(marketing) == 2
    assert all(item["policy"]["allowed"] for item in marketing)
    assert all(SPECIAL_LINK in item["content"] for item in marketing)
    assert all("As an Amazon Associate I earn from qualifying purchases" in item["content"] for item in marketing)
    assert all("/r/" not in item["content"] and "utm_" not in item["content"] for item in marketing)

    reviewed = client.post(
        f"/api/artifacts/{marketing[0]['id']}/review",
        headers=control(),
        json={"decision": "approved", "reviewer": "test-owner", "notes": "link and disclosure checked"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "approved"


def test_missing_amazon_special_link_blocks_marketing_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    configure_environment(tmp_path, monkeypatch, special_link="")
    with TestClient(create_app()) as test_client:
        run = test_client.post(
            f"/api/campaigns/{SLUG}/runs",
            headers=control(),
            json={"workflow": "content", "channels": ["landing_page"], "force": True},
        )
        assert run.status_code == 200
        artifact = test_client.get(
            f"/api/campaigns/{SLUG}/artifacts", headers=control()
        ).json()["artifacts"][0]
        assert artifact["policy"]["allowed"] is False
        assert any(finding["code"] == "amazon_special_link_missing" for finding in artifact["policy"]["findings"])


def test_legacy_paypro_and_redirect_endpoints_are_disabled_for_amazon(client: TestClient):
    callback = client.post("/api/webhooks/paypro", content=b"{}")
    assert callback.status_code == 410
    redirect = client.get(f"/r/{SLUG}?src=social&content=post-1", follow_redirects=False)
    assert redirect.status_code == 410


def test_generic_webhook_deduplicates_external_event(client: TestClient):
    payload = {
        "provider": "manual-report-import",
        "event": {
            "campaign_slug": SLUG,
            "event_type": "conversion",
            "source": "amazon_report",
            "medium": "affiliate",
            "event_id": "amazon-report-row-1",
            "value": 19.0,
            "metadata": {"verification": "owner-reviewed-report"},
        },
    }
    headers = {"X-Webhook-Token": "test-webhook-token"}
    first = client.post("/api/webhooks/events", headers=headers, json=payload)
    second = client.post("/api/webhooks/events", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    metrics = client.get(f"/api/campaigns/{SLUG}/analytics", headers=control()).json()
    assert metrics["conversions"] == 1


def test_clone_campaign_and_decide_optimization(client: TestClient):
    cloned = client.post(
        f"/api/campaigns/{SLUG}/clone",
        headers=control(),
        json={
            "name": "Alternative bottle test",
            "slug": "alternative-bottle-test",
            "product_name": "Alternative product",
            "product_url": "https://www.amazon.com/dp/B0BZYCJK89?tag=spmg00-20",
            "reset_product_facts": True,
        },
    )
    assert cloned.status_code == 201
    assert cloned.json()["product_facts"] == []

    run = client.post(
        f"/api/campaigns/{SLUG}/runs", headers=control(), json={"workflow": "analytics", "force": True}
    )
    assert run.status_code == 200
    proposals = client.get(f"/api/campaigns/{SLUG}/optimizations", headers=control()).json()["proposals"]
    assert proposals
    decision = client.post(
        f"/api/optimizations/{proposals[0]['id']}/decision",
        headers=control(),
        json={"decision": "accepted", "reviewer": "owner", "notes": "test"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "accepted"


def test_public_site_is_disabled_by_default(client: TestClient):
    response = client.get(f"/site/{SLUG}")
    assert response.status_code == 404


def test_public_site_renders_only_approved_drafts_with_direct_link(publisher_client: TestClient):
    run = publisher_client.post(
        f"/api/campaigns/{SLUG}/runs",
        headers=control(),
        json={"workflow": "content", "channels": ["landing_page", "blog"], "force": True},
    )
    assert run.status_code == 200
    artifacts = publisher_client.get(f"/api/campaigns/{SLUG}/artifacts", headers=control()).json()["artifacts"]
    draft_blog = next(item for item in artifacts if item["artifact_type"] == "blog_article")
    assert publisher_client.get(f"/site/{SLUG}/articles/{draft_blog['id']}").status_code == 404

    for artifact in artifacts:
        reviewed = publisher_client.post(
            f"/api/artifacts/{artifact['id']}/review",
            headers=control(),
            json={"decision": "approved", "reviewer": "test-owner", "notes": "link, claims, and disclosure reviewed"},
        )
        assert reviewed.status_code == 200

    site = publisher_client.get(f"/site/{SLUG}")
    assert site.status_code == 200
    assert "Practical product research" in site.text
    assert SPECIAL_LINK in site.text
    assert "As an Amazon Associate I earn from qualifying purchases" in site.text
    assert "/r/" not in site.text

    article = publisher_client.get(f"/site/{SLUG}/articles/{draft_blog['id']}")
    assert article.status_code == 200
    assert "What to check before choosing" in article.text
    status = publisher_client.get("/api/publisher/status", headers=control())
    assert status.status_code == 200
    assert status.json()["approved_artifact_count"] == 4


def test_public_creative_page_uses_direct_special_link(publisher_client: TestClient):
    publisher_client.post(
        f"/api/campaigns/{SLUG}/runs",
        headers=control(),
        json={"workflow": "content", "channels": ["landing_page"], "force": True},
    )
    artifact = publisher_client.get(f"/api/campaigns/{SLUG}/artifacts", headers=control()).json()["artifacts"][0]
    publisher_client.post(
        f"/api/artifacts/{artifact['id']}/review",
        headers=control(),
        json={"decision": "approved", "reviewer": "test-owner", "notes": "approved"},
    )
    page = publisher_client.get(f"/site/{SLUG}/c/daily-carry-social")
    assert page.status_code == 200
    assert SPECIAL_LINK in page.text
    assert "/r/" not in page.text


def test_public_portfolio_lists_active_approved_campaigns_only(publisher_client: TestClient):
    assert "Owala FreeSip" not in publisher_client.get("/site").text
    publisher_client.patch(f"/api/campaigns/{SLUG}", headers=control(), json={"status": "active"})
    publisher_client.post(
        f"/api/campaigns/{SLUG}/runs",
        headers=control(),
        json={"workflow": "content", "channels": ["landing_page"], "force": True},
    )
    landing = publisher_client.get(f"/api/campaigns/{SLUG}/artifacts", headers=control()).json()["artifacts"][0]
    publisher_client.post(
        f"/api/artifacts/{landing['id']}/review",
        headers=control(),
        json={"decision": "approved", "reviewer": "test-owner", "notes": "checked"},
    )
    portfolio = publisher_client.get("/site")
    assert portfolio.status_code == 200
    assert "Owala FreeSip Stainless Steel Water Bottle, 24 oz" in portfolio.text
    assert f"/site/{SLUG}" in portfolio.text
