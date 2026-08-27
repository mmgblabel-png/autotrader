"""Typed contracts for campaigns, runs, artifacts, approvals, and tracking events."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class Channel(StrEnum):
    BLOG = "blog"
    EMAIL = "email"
    SOCIAL = "social"
    LANDING_PAGE = "landing_page"
    COMMUNITY = "community"
    SEO = "seo"


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    product_name: str = Field(default="WegMetDieKilos – Bronze Plan", max_length=160)
    product_url: HttpUrl | None = None
    audience: str = Field(min_length=10, max_length=2000)
    market: str = Field(default="Nederland", max_length=120)
    language: str = Field(default="nl-NL", max_length=20)
    channels: list[Channel] = Field(
        default_factory=lambda: [Channel.BLOG, Channel.EMAIL, Channel.SOCIAL]
    )
    goals: list[str] = Field(default_factory=lambda: ["kwalitatieve opt-in leads"])
    product_facts: list[str] = Field(default_factory=list, max_length=30)
    prohibited_claims: list[str] = Field(default_factory=list, max_length=30)
    schedule_cron: str = Field(default="0 9 * * 1", min_length=5, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("channels")
    @classmethod
    def channels_must_not_be_empty(cls, value: list[Channel]) -> list[Channel]:
        if not value:
            raise ValueError("at least one channel is required")
        return list(dict.fromkeys(value))


class CampaignUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CampaignStatus | None = None
    audience: str | None = Field(default=None, min_length=10, max_length=2000)
    channels: list[Channel] | None = None
    goals: list[str] | None = None
    product_facts: list[str] | None = None
    prohibited_claims: list[str] | None = None
    schedule_cron: str | None = Field(default=None, min_length=5, max_length=80)
    metadata: dict[str, Any] | None = None


class CampaignCloneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    product_name: str | None = Field(default=None, max_length=160)
    product_url: HttpUrl | None = None
    audience: str | None = Field(default=None, min_length=10, max_length=2000)
    reset_product_facts: bool = True


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: str = Field(default="full_campaign", pattern=r"^[a-z_]+$", max_length=50)
    channels: list[Channel] | None = None
    force: bool = False


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ArtifactStatus
    reviewer: str = Field(default="owner", min_length=2, max_length=100)
    notes: str = Field(default="", max_length=2000)

    @field_validator("decision")
    @classmethod
    def only_terminal_decisions(cls, value: ArtifactStatus) -> ArtifactStatus:
        if value == ArtifactStatus.DRAFT:
            raise ValueError("decision must be approved or rejected")
        return value


class OptimizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(accepted|rejected)$")
    reviewer: str = Field(default="owner", min_length=2, max_length=100)
    notes: str = Field(default="", max_length=2000)


class TrackingEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    event_type: str = Field(pattern=r"^(click|conversion|signup|view)$")
    source: str = Field(default="unknown", max_length=100)
    medium: str = Field(default="unknown", max_length=100)
    content_id: str = Field(default="", max_length=100)
    event_id: str = Field(default="", max_length=120)
    value: float = Field(default=0.0, ge=0.0, le=1_000_000.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def metadata_must_be_pseudonymous(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {
            "name",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "telephone",
            "ip",
            "ip_address",
            "bsn",
            "health",
            "medical",
            "diagnosis",
        }

        def inspect(item: Any, path: tuple[str, ...] = ()) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    normalized = str(key).strip().lower()
                    if normalized in forbidden:
                        raise ValueError(
                            f"tracking metadata contains prohibited direct identifier: {'.'.join((*path, normalized))}"
                        )
                    inspect(child, (*path, normalized))
            elif isinstance(item, list):
                for child in item:
                    inspect(child, path)
            elif isinstance(item, str) and re.search(
                r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", item, re.IGNORECASE
            ):
                raise ValueError("tracking metadata must not contain email addresses")

        inspect(value)
        return value


class WebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: TrackingEventCreate
    provider: str = Field(default="custom", min_length=2, max_length=80)
    occurred_at: datetime | None = None


class PolicyFinding(BaseModel):
    code: str
    severity: str
    message: str


class PolicyResult(BaseModel):
    allowed: bool
    findings: list[PolicyFinding] = Field(default_factory=list)
    disclosure_added: bool = False


class AgentResult(BaseModel):
    agent: str
    objective: str
    summary: str
    payload: dict[str, Any]
    confidence: float = Field(ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    sources_needed: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    draft_only: bool
    llm_mode: str
    database_ok: bool
    heartbeat: dict[str, Any]
