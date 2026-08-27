"""FastAPI control plane and public tracking endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from campaign_automaton.models import (
    ApprovalRequest,
    CampaignCloneRequest,
    CampaignCreate,
    CampaignUpdate,
    HealthResponse,
    OptimizationDecision,
    RunRequest,
    TrackingEventCreate,
    WebhookEvent,
)
from campaign_automaton.publisher import (
    _ALLOWED_MEDIA,
    _ALLOWED_SOURCES,
    PublicPublisher,
    safe_content_id,
    safe_tracking_value,
)
from campaign_automaton.runtime import Runtime, build_runtime
from campaign_automaton.store import StoreError

VERSION = "1.0.0"


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def _constant_time_token(provided: str | None, expected: str, label: str) -> None:
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} is disabled until its server-side token is configured.",
        )
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")


def require_control(
    request: Request,
    x_control_token: Annotated[str | None, Header()] = None,
) -> None:
    _constant_time_token(x_control_token, get_runtime(request).settings.control_token, "Control API")


def require_webhook(
    request: Request,
    x_webhook_token: Annotated[str | None, Header()] = None,
) -> None:
    _constant_time_token(x_webhook_token, get_runtime(request).settings.webhook_token, "Webhook")


def _paypro_signature_is_valid(
    raw_body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str,
) -> bool:
    """Verify PayPro's HMAC-SHA256 over `<timestamp>.<unaltered JSON body>` within ten minutes."""
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = float(timestamp)
    except ValueError:
        return False
    if abs(time.time() - sent_at) > 600:
        return False
    payload = timestamp.encode("utf-8") + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = build_runtime()
    app.state.runtime = runtime
    await runtime.scheduler.start()
    try:
        yield
    finally:
        await runtime.scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="WegMetDieKilos Campaign Automaton API",
        version=VERSION,
        description=(
            "Approval-gated campaign generation, affiliate tracking, analytics, and optimization."
        ),
        lifespan=lifespan,
    )
    runtime_settings = None
    try:
        from campaign_automaton.config import load_settings

        runtime_settings = load_settings()
    except Exception:
        runtime_settings = None
    origins = list(runtime_settings.cors_origins) if runtime_settings else ["http://localhost:3000"]
    for development_origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        if development_origin not in origins:
            origins.append(development_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=r"^https://[a-z0-9.-]+\.manus\.(?:space|computer)$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Control-Token", "X-Webhook-Token", "Idempotency-Key"],
    )
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.exception_handler(StoreError)
    async def store_error_handler(_: Request, exc: StoreError):
        return __import__("fastapi").responses.JSONResponse(
            status_code=404 if "not found" in str(exc) else 409,
            content={"detail": str(exc)},
        )

    @app.get("/", tags=["health"])
    def root() -> dict[str, Any]:
        return {
            "service": "WegMetDieKilos Campaign Automaton",
            "version": VERSION,
            "docs": "/docs",
            "health": "/api/health",
            "mode": "approval-gated",
        }

    @app.get("/site", response_class=HTMLResponse, include_in_schema=False)
    def public_portfolio(request: Request) -> HTMLResponse:
        publisher = PublicPublisher(get_runtime(request).settings, get_runtime(request).store)
        if not publisher.enabled():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public site is not enabled.")
        return HTMLResponse(publisher.portfolio())

    @app.get("/site/{campaign_slug}", response_class=HTMLResponse, include_in_schema=False)
    def public_site(
        campaign_slug: str,
        request: Request,
        utm_source: str = Query(default="website", max_length=100),
        utm_medium: str = Query(default="referral", max_length=100),
        utm_content: str = Query(default="hero-cta", max_length=100),
    ) -> HTMLResponse:
        publisher = PublicPublisher(get_runtime(request).settings, get_runtime(request).store)
        if not publisher.enabled():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public site is not enabled.")
        return HTMLResponse(
            publisher.home(
                campaign_slug,
                safe_tracking_value(utm_source, allowed=_ALLOWED_SOURCES, fallback="website"),
                safe_tracking_value(utm_medium, allowed=_ALLOWED_MEDIA, fallback="referral"),
                safe_content_id(utm_content),
            )
        )

    @app.get("/site/{campaign_slug}/c/{creative_id}", response_class=HTMLResponse, include_in_schema=False)
    def public_creative(
        campaign_slug: str,
        creative_id: str,
        request: Request,
    ) -> HTMLResponse:
        publisher = PublicPublisher(get_runtime(request).settings, get_runtime(request).store)
        if not publisher.enabled():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public site is not enabled.")
        creative = publisher.creative(campaign_slug, creative_id)
        if creative is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creative page not found.")
        return HTMLResponse(creative)

    @app.get("/site/{campaign_slug}/articles/{artifact_id}", response_class=HTMLResponse, include_in_schema=False)
    def public_article(campaign_slug: str, artifact_id: str, request: Request) -> HTMLResponse:
        publisher = PublicPublisher(get_runtime(request).settings, get_runtime(request).store)
        if not publisher.enabled():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public site is not enabled.")
        artifact = publisher.article(campaign_slug, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published article not found.")
        return HTMLResponse(publisher.article_page(campaign_slug, artifact))

    @app.get("/api/publisher/status", tags=["publisher"])
    def publisher_status(
        request: Request,
        campaign_slug: str = "wegmetdiekilos-bronze",
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return PublicPublisher(get_runtime(request).settings, get_runtime(request).store).status(
            campaign_slug
        )

    @app.get("/api/health", response_model=HealthResponse, tags=["health"])
    def health(request: Request) -> HealthResponse:
        runtime = get_runtime(request)
        return HealthResponse(
            status="ok",
            service=runtime.settings.app_name,
            version=VERSION,
            environment=runtime.settings.app_env,
            draft_only=runtime.settings.draft_only,
            llm_mode=runtime.llm.mode,
            database_ok=runtime.store.health(),
            heartbeat=runtime.scheduler.status(),
        )

    @app.get("/api/public/farm-snapshot", tags=["public"])
    def public_farm_snapshot(request: Request) -> dict[str, Any]:
        """Return aggregated public portfolio data for the read-only Event Farm game.

        The endpoint deliberately excludes affiliate destinations, content drafts, audit notes,
        tokens, personal information, and raw event metadata. Source attribution is exposed only
        as a small allowlisted channel taxonomy with aggregate counts, making it safe for a public
        browser game to request on load and every 60 seconds while the page remains open.
        """
        runtime = get_runtime(request)
        now = datetime.now(UTC)
        verification_sources = {
            "railway-live-verification",
            "website-live-verification",
            "internal-verification",
        }
        public_source_labels = {
            "railway-live-verification": "Railway verification",
            "website-live-verification": "Website verification",
            "internal-verification": "Internal verification",
            "direct": "Direct visit",
            "organic": "Organic search",
            "google": "Google search",
            "social": "Social media",
            "facebook": "Facebook",
            "instagram": "Instagram",
            "linkedin": "LinkedIn",
            "email": "Email newsletter",
            "newsletter": "Email newsletter",
            "website": "Website referral",
            "paypro": "PayPro referral",
        }
        public_medium_labels = {
            "affiliate": "Affiliate",
            "social": "Social",
            "email": "Email",
            "organic": "Organic",
            "referral": "Referral",
            "paid": "Paid campaign",
            "display": "Display",
        }
        metric_names = ("views", "clicks", "signups", "conversions")

        def empty_metrics() -> dict[str, int]:
            return {metric: 0 for metric in metric_names}

        def public_source(source: Any) -> str:
            normalized = str(source or "").strip().lower()
            return public_source_labels.get(normalized, "Other tracked source")

        campaigns: list[dict[str, Any]] = []
        active_campaign_ids: list[str] = []
        totals = empty_metrics()
        source_totals: dict[str, dict[str, int]] = {}
        attribution_totals: dict[tuple[str, str, str, str, str], dict[str, int]] = {}
        history_totals: dict[str, dict[str, int]] = {}
        next_run_times: list[datetime] = []
        for campaign in runtime.store.list_campaigns():
            if campaign["status"] != "active":
                continue
            active_campaign_ids.append(campaign["id"])
            metrics = runtime.store.campaign_metrics(campaign["id"])
            sources = {row["source"] for row in metrics["by_source"]}
            if not sources:
                data_quality = "no_events"
            elif sources.issubset(verification_sources):
                data_quality = "verification_only"
            else:
                data_quality = "observed_events"
            public_metrics = {metric: int(metrics[metric]) for metric in metric_names}
            for metric, value in public_metrics.items():
                totals[metric] += value
            source_metrics: dict[str, dict[str, int]] = {}
            for row in metrics["by_source"]:
                label = public_source(row["source"])
                source_metrics.setdefault(label, empty_metrics())
                source_totals.setdefault(label, empty_metrics())
                event_type = str(row["event_type"])
                if "." in event_type:
                    event_type = event_type.rsplit(".", maxsplit=1)[-1].lower()
                metric_key = {
                    "view": "views",
                    "click": "clicks",
                    "signup": "signups",
                    "conversion": "conversions",
                }.get(event_type)
                if metric_key:
                    count = int(row["count"])
                    source_metrics[label][metric_key] += count
                    source_totals[label][metric_key] += count
            attribution_metrics: dict[tuple[str, str, str], dict[str, int]] = {}
            for row in runtime.store.campaign_attribution(campaign["id"]):
                source_label = public_source(row["source"])
                medium_label = public_medium_labels.get(str(row["medium"]).lower(), "Other channel")
                content_id = safe_content_id(str(row["content_id"]), fallback="Unlabeled asset")
                attribution_key = (source_label, medium_label, content_id)
                portfolio_attribution_key = (
                    campaign["slug"],
                    campaign["product_name"],
                    source_label,
                    medium_label,
                    content_id,
                )
                attribution_metrics.setdefault(attribution_key, empty_metrics())
                attribution_totals.setdefault(portfolio_attribution_key, empty_metrics())
                event_type = str(row["event_type"]).rsplit(".", maxsplit=1)[-1].lower()
                metric_key = {
                    "view": "views", "click": "clicks", "signup": "signups", "conversion": "conversions"
                }.get(event_type)
                if metric_key:
                    count = int(row["count"])
                    attribution_metrics[attribution_key][metric_key] += count
                    attribution_totals[portfolio_attribution_key][metric_key] += count
            history = runtime.store.campaign_daily_metrics(campaign["id"])
            for point in history:
                history_totals.setdefault(point["date"], empty_metrics())
                for metric, value in point["metrics"].items():
                    history_totals[point["date"]][metric] += int(value)
            next_run_at = campaign.get("next_run_at")
            if next_run_at:
                next_run_times.append(datetime.fromisoformat(next_run_at).astimezone(UTC))
            campaigns.append(
                {
                    "slug": campaign["slug"],
                    "product_name": campaign["product_name"],
                    "metrics": public_metrics,
                    "data_quality": data_quality,
                    "next_run_at": next_run_at,
                    "source_breakdown": [
                        {"source": label, "metrics": values}
                        for label, values in sorted(
                            source_metrics.items(),
                            key=lambda item: sum(item[1].values()),
                            reverse=True,
                        )
                    ],
                    "attribution_breakdown": [
                        {
                            "campaign_slug": campaign["slug"],
                            "campaign_name": campaign["product_name"],
                            "source": key[0],
                            "medium": key[1],
                            "content": key[2],
                            "metrics": values,
                        }
                        for key, values in sorted(
                            attribution_metrics.items(),
                            key=lambda item: sum(item[1].values()),
                            reverse=True,
                        )
                    ],
                    "history": history,
                }
            )
        snapshot_quality = (
            "verification_only"
            if campaigns and all(row["data_quality"] == "verification_only" for row in campaigns)
            else "mixed_or_observed"
        )
        next_scheduled_review = min(next_run_times) if next_run_times else now + timedelta(hours=24)
        verified_conversions = runtime.store.verified_conversion_summary(active_campaign_ids)
        verified_at = verified_conversions["latest_at"]
        if verified_at:
            review_started_at = datetime.fromisoformat(verified_at).astimezone(UTC)
            review_at = review_started_at + timedelta(hours=24)
        else:
            review_at = next_scheduled_review
            review_started_at = review_at - timedelta(hours=24)
        campaign_count = max(1, len(campaigns))
        required_views = 100 * campaign_count
        required_clicks = 20 * campaign_count
        view_progress = min(1.0, totals["views"] / required_views)
        click_progress = min(1.0, totals["clicks"] / required_clicks)
        evidence_progress = int(min(view_progress, click_progress) * 100)
        learning_state = (
            "verification_only"
            if snapshot_quality == "verification_only"
            else "reviewable" if evidence_progress == 100 else "collecting_evidence"
        )
        return {
            "schema_version": 1,
            "refreshed_at": now.isoformat(),
            "refresh_interval_seconds": 60,
            "data_quality": snapshot_quality,
            "lifecycle": totals,
            "campaigns": campaigns,
            "source_breakdown": [
                {"source": label, "metrics": values}
                for label, values in sorted(
                    source_totals.items(), key=lambda item: sum(item[1].values()), reverse=True
                )
            ],
            "attribution_breakdown": [
                {
                    "campaign_slug": key[0],
                    "campaign_name": key[1],
                    "source": key[2],
                    "medium": key[3],
                    "content": key[4],
                    "metrics": values,
                }
                for key, values in sorted(
                    attribution_totals.items(), key=lambda item: sum(item[1].values()), reverse=True
                )
            ],
            "history": [
                {"date": day, "metrics": values}
                for day, values in sorted(history_totals.items())
            ],
            "review_window": {
                "hours": 24,
                "started_at": review_started_at.isoformat(),
                "review_at": review_at.isoformat(),
                "minimum_views_per_campaign": 100,
                "minimum_clicks_per_campaign": 20,
                "verified_conversion_count": verified_conversions["count"],
                "last_verified_conversion_at": verified_at,
                "learning_state": learning_state,
                "evidence_progress_percent": evidence_progress,
                "strategy_change_allowed": learning_state == "reviewable",
                "recommendation": (
                    "Collect evidence before proposing a reversible, owner-approved strategy change."
                ),
            },
        }

    @app.get("/api/config/status", tags=["health"])
    def config_status(
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        return {
            "affiliate": runtime.links.affiliate_status(),
            "draft_only": runtime.settings.draft_only,
            "llm_mode": runtime.llm.mode,
            "llm_model": runtime.settings.llm_model,
            "auto_run_due_campaigns": runtime.settings.auto_run_due_campaigns,
            "hourly_sales_review_enabled": runtime.settings.hourly_sales_review_enabled,
            "website_enabled": runtime.settings.website_enabled,
            "data_dir": str(runtime.settings.data_dir),
        }

    @app.get("/api/campaigns", tags=["campaigns"])
    def list_campaigns(
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return {"campaigns": get_runtime(request).store.list_campaigns()}

    @app.post("/api/campaigns", status_code=201, tags=["campaigns"])
    def create_campaign(
        payload: CampaignCreate,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        product_url = str(payload.product_url or runtime.settings.paypro_product_url)
        return runtime.store.create_campaign(payload, product_url)

    @app.post("/api/campaigns/{slug}/clone", status_code=201, tags=["campaigns"])
    def clone_campaign(
        slug: str,
        payload: CampaignCloneRequest,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        product_url = str(payload.product_url or runtime.settings.paypro_product_url)
        return runtime.store.clone_campaign(slug, payload, product_url)

    @app.get("/api/campaigns/{slug}", tags=["campaigns"])
    def get_campaign(
        slug: str,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return get_runtime(request).store.get_campaign(slug)

    @app.patch("/api/campaigns/{slug}", tags=["campaigns"])
    def update_campaign(
        slug: str,
        payload: CampaignUpdate,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return get_runtime(request).store.update_campaign(slug, payload)

    @app.post("/api/campaigns/{slug}/runs", tags=["runs"])
    def run_campaign(
        slug: str,
        payload: RunRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header()] = None,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return get_runtime(request).orchestrator.run_now(slug, payload, idempotency_key)

    @app.get("/api/campaigns/{slug}/runs", tags=["runs"])
    def list_runs(
        slug: str,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(slug)
        return {"runs": runtime.store.list_runs(campaign["id"], limit)}

    @app.get("/api/runs/{run_id}", tags=["runs"])
    def get_run(
        run_id: str,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return get_runtime(request).store.get_run(run_id)

    @app.get("/api/campaigns/{slug}/artifacts", tags=["artifacts"])
    def list_artifacts(
        slug: str,
        request: Request,
        artifact_status: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=100, ge=1, le=500),
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(slug)
        return {
            "artifacts": runtime.store.list_artifacts(
                campaign["id"], status=artifact_status, limit=limit
            )
        }

    @app.get("/api/artifacts/{artifact_id}", tags=["artifacts"])
    def get_artifact(
        artifact_id: str,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return get_runtime(request).store.get_artifact(artifact_id)

    @app.post("/api/artifacts/{artifact_id}/review", tags=["artifacts"])
    def review_artifact(
        artifact_id: str,
        payload: ApprovalRequest,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        artifact = runtime.store.get_artifact(artifact_id)
        if payload.decision == "approved" and not artifact["policy"].get("allowed", False):
            raise HTTPException(
                status_code=409,
                detail="This artifact has blocking policy findings and cannot be approved.",
            )
        return runtime.store.review_artifact(
            artifact_id, payload.decision, payload.reviewer, payload.notes
        )

    @app.get("/api/campaigns/{slug}/analytics", tags=["analytics"])
    def analytics(
        slug: str,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(slug)
        return runtime.store.campaign_metrics(campaign["id"])

    @app.get("/api/campaigns/{slug}/hourly-reviews", tags=["analytics"])
    def hourly_sales_reviews(
        slug: str,
        request: Request,
        limit: int = Query(default=72, ge=1, le=720),
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        """Return durable internal reviews; this never triggers a campaign action."""
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(slug)
        return {"reviews": runtime.store.list_hourly_sales_reviews(campaign["id"], limit)}

    @app.get("/api/campaigns/{slug}/hourly-reviews/latest", tags=["analytics"])
    def latest_hourly_sales_review(
        slug: str,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        """Return the latest internal review or an explicit empty-state response."""
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(slug)
        review = runtime.store.latest_hourly_sales_review(campaign["id"])
        if review is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No hourly sales review has been created for this campaign.",
            )
        return review

    @app.get("/api/campaigns/{slug}/optimizations", tags=["analytics"])
    def optimization_proposals(
        slug: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(slug)
        return {
            "proposals": runtime.store.list_optimization_proposals(campaign["id"], limit)
        }

    @app.post("/api/optimizations/{proposal_id}/decision", tags=["analytics"])
    def decide_optimization(
        proposal_id: str,
        payload: OptimizationDecision,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        return get_runtime(request).store.decide_optimization(
            proposal_id, payload.decision, payload.reviewer, payload.notes
        )

    @app.get("/api/audit", tags=["audit"])
    def audit(
        request: Request,
        campaign_slug: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        campaign_id = None
        if campaign_slug:
            campaign_id = runtime.store.get_campaign(campaign_slug)["id"]
        return {"events": runtime.store.list_audit(campaign_id, limit)}

    @app.post("/api/events", status_code=201, tags=["analytics"])
    def record_event(
        payload: TrackingEventCreate,
        request: Request,
        _: None = Depends(require_control),
    ) -> dict[str, Any]:
        event, created = get_runtime(request).store.record_tracking_event(payload)
        return {"created": created, "event": event}

    @app.post("/api/webhooks/events", tags=["webhooks"])
    def webhook_event(
        payload: WebhookEvent,
        request: Request,
        _: None = Depends(require_webhook),
    ) -> dict[str, Any]:
        runtime = get_runtime(request)
        event, created = runtime.store.record_tracking_event(payload.event)
        runtime.store.audit(
            event["campaign_id"], payload.provider, "webhook.event", "tracking_event",
            event["id"], {"created": created, "occurred_at": payload.occurred_at},
        )
        return {"accepted": True, "created": created, "event_id": event["id"]}

    @app.post("/api/webhooks/paypro", tags=["webhooks"])
    async def paypro_webhook(
        request: Request,
        paypro_signature: Annotated[str | None, Header()] = None,
        paypro_timestamp: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        """Accept only current, signed `payment.paid` events and deduplicate with PayPro's event ID."""
        runtime = get_runtime(request)
        raw_body = await request.body()
        if not runtime.settings.paypro_webhook_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="PayPro callback is disabled until PAYPRO_WEBHOOK_SECRET is configured.",
            )
        if not _paypro_signature_is_valid(
            raw_body, paypro_timestamp, paypro_signature, runtime.settings.paypro_webhook_secret
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid PayPro webhook signature.")
        try:
            event = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.") from exc
        if event.get("event_type") != "payment.paid":
            return {"accepted": True, "created": False, "ignored": "unsupported_event"}
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        campaign_slug = str(metadata.get("campaign_slug") or payload.get("campaign_slug") or "")
        external_event_id = str(event.get("id") or "")
        if not campaign_slug or not external_event_id:
            return {"accepted": True, "created": False, "ignored": "missing_attribution"}
        tracking_event = TrackingEventCreate(
            campaign_slug=campaign_slug,
            event_type="conversion",
            source="paypro",
            medium="affiliate",
            content_id=safe_content_id(str(metadata.get("utm_content") or "paypro-paid")),
            event_id=external_event_id,
            metadata={"verification": "paypro_hmac", "event_type": "payment.paid"},
        )
        stored, created = runtime.store.record_tracking_event(tracking_event)
        runtime.store.audit(
            stored["campaign_id"],
            "paypro",
            "webhook.payment_paid",
            "tracking_event",
            stored["id"],
            {"created": created, "verified": True},
        )
        return {"accepted": True, "created": created, "event_id": stored["id"]}

    @app.get("/r/{campaign_slug}", include_in_schema=False)
    def tracked_redirect(
        campaign_slug: str,
        request: Request,
        src: str = Query(default="unknown", max_length=100),
        medium: str = Query(default="affiliate", max_length=100),
        content: str = Query(default="", max_length=100),
    ) -> RedirectResponse:
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(campaign_slug)
        event = TrackingEventCreate(
            campaign_slug=campaign_slug,
            event_type="click",
            source=safe_tracking_value(src, allowed=_ALLOWED_SOURCES, fallback="website"),
            medium=safe_tracking_value(medium, allowed=_ALLOWED_MEDIA, fallback="affiliate"),
            content_id=safe_content_id(content),
            metadata={"tracking": "first_party_redirect"},
        )
        runtime.store.record_tracking_event(event)
        destination = runtime.links.destination(
            campaign,
            safe_tracking_value(src, allowed=_ALLOWED_SOURCES, fallback="website"),
            safe_content_id(content),
            safe_tracking_value(medium, allowed=_ALLOWED_MEDIA, fallback="affiliate"),
        )
        return RedirectResponse(destination, status_code=302)

    return app


app = create_app()
