"""FastAPI control plane and public tracking endpoints."""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
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
from campaign_automaton.publisher import PublicPublisher
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
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
    def public_site(campaign_slug: str, request: Request) -> HTMLResponse:
        publisher = PublicPublisher(get_runtime(request).settings, get_runtime(request).store)
        if not publisher.enabled():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Public site is not enabled.")
        return HTMLResponse(publisher.home(campaign_slug))

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

    @app.get("/r/{campaign_slug}", include_in_schema=False)
    def tracked_redirect(
        campaign_slug: str,
        request: Request,
        src: str = Query(default="unknown", max_length=100),
        content: str = Query(default="", max_length=100),
    ) -> RedirectResponse:
        runtime = get_runtime(request)
        campaign = runtime.store.get_campaign(campaign_slug)
        event = TrackingEventCreate(
            campaign_slug=campaign_slug,
            event_type="click",
            source=src,
            medium="affiliate",
            content_id=content,
            metadata={"tracking": "first_party_redirect"},
        )
        runtime.store.record_tracking_event(event)
        destination = runtime.links.destination(campaign, src, content)
        return RedirectResponse(destination, status_code=302)

    return app


app = create_app()
